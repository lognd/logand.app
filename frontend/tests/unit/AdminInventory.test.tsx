import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminInventory } from "../../src/app/routes/admin/Inventory";
import type { InventoryItem } from "../../src/api/inventory";

// Integration-layer test per docs/design/12: real api/inventory.ts
// module, only the underlying fetch() is mocked -- proves the confirm+
// diff adjustment UI, TanStack Query wiring, and the API module's real
// query-param/JSON-body request shaping all work together.

const widget: InventoryItem = {
  id: "item-1",
  name: "widget",
  description: null,
  quantity: 10,
  location_id: "loc-1",
  tags: [],
  unit_cost: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminInventory />
    </QueryClientProvider>,
  );
}

describe("AdminInventory adjustment flow (integration)", () => {
  beforeEach(() => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign: vi.fn() },
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a real before-to-after diff before allowing confirmation, and sends the real adjust request", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/admin/inventory/items" && (!init || init.method === "GET")) {
        return Promise.resolve(jsonResponse([widget]));
      }
      if (url === "/api/admin/inventory/items/item-1/adjust") {
        return Promise.resolve(jsonResponse({ id: "adj-1" }));
      }
      return Promise.resolve(jsonResponse([]));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Adjust quantity for widget" }),
    );

    const deltaInput = screen.getByLabelText("Change by");
    const reasonInput = screen.getByLabelText("Reason");
    const confirmButton = screen.getByRole("button", { name: "Confirm adjustment" });

    // Not confirmable yet -- no delta/reason entered.
    expect(confirmButton).toBeDisabled();

    await user.type(deltaInput, "-3");
    // The real diff, computed from the item's actual current quantity
    // (10), not just echoing back the typed delta.
    expect(await screen.findByTestId("diff-item-1")).toHaveTextContent(
      "Quantity will change from 10 to 7",
    );
    // Still not confirmable -- delta given but no reason yet.
    expect(confirmButton).toBeDisabled();

    await user.type(reasonInput, "sold at market");
    expect(confirmButton).toBeEnabled();

    await user.click(confirmButton);

    await waitFor(() => {
      const adjustCall = fetchMock.mock.calls.find(
        ([url]) => url === "/api/admin/inventory/items/item-1/adjust",
      ) as [string, RequestInit] | undefined;
      expect(adjustCall).toBeDefined();
      const [, init] = adjustCall!;
      expect(JSON.parse(String(init.body))).toEqual({
        delta: -3,
        reason: "sold at market",
      });
    });
  });

  it("disables confirmation for an adjustment that would take quantity below zero", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/admin/inventory/items") {
        return Promise.resolve(jsonResponse([widget]));
      }
      return Promise.resolve(jsonResponse([]));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "Adjust quantity for widget" }),
    );
    await user.type(screen.getByLabelText("Change by"), "-100");
    await user.type(screen.getByLabelText("Reason"), "too many");

    expect(await screen.findByTestId("diff-item-1")).toHaveTextContent(
      "not allowed, quantity can't go below zero",
    );
    expect(screen.getByRole("button", { name: "Confirm adjustment" })).toBeDisabled();
  });
});
