import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminData } from "../../src/app/routes/admin/AdminData";

// Integration-layer test per docs/design/12: real api/adminData.ts module,
// only fetch() is mocked -- proves the confirm-before-write flow (the
// site-wide "confirmations on everything" requirement) fires the real
// PATCH only after an explicit second click showing the exact before/after
// diff, not a generic "are you sure".

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminData />
    </QueryClientProvider>,
  );
}

describe("AdminData (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("editing a row shows an exact before-to-after diff before the real PATCH fires", async () => {
    const row = { id: "item-1", name: "widget", quantity: 10 };
    const schema = [
      { name: "id", type: "UUID", nullable: false, primary_key: true, editable: false },
      {
        name: "name",
        type: "VARCHAR",
        nullable: false,
        primary_key: false,
        editable: true,
      },
      {
        name: "quantity",
        type: "INTEGER",
        nullable: false,
        primary_key: false,
        editable: true,
      },
    ];
    const fetchMock = vi.fn((url: string) => {
      if (url.startsWith("/api/admin/data/tables/inventory_items/rows/item-1")) {
        if (url.includes("change_id")) return Promise.resolve(jsonResponse({}));
        return Promise.resolve(jsonResponse(row));
      }
      if (url.startsWith("/api/admin/data/tables/inventory_items/schema")) {
        return Promise.resolve(jsonResponse(schema));
      }
      if (url.startsWith("/api/admin/data/tables/inventory_items/rows")) {
        return Promise.resolve(jsonResponse([row]));
      }
      if (url === "/api/admin/data/tables") {
        return Promise.resolve(jsonResponse(["inventory_items"]));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await screen.findByRole("option", { name: "inventory_items" });
    await user.selectOptions(screen.getByLabelText("Table"), "inventory_items");
    await user.click(await screen.findByRole("button", { name: "item-1" }));

    const quantityInput = await screen.findByLabelText("quantity");
    await user.clear(quantityInput);
    await user.type(quantityInput, "42");

    await user.click(await screen.findByRole("button", { name: "Review changes" }));

    expect(await screen.findByText(/Confirm the following change/)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).startsWith("/api/admin/data/tables/inventory_items/rows/item-1") &&
          (init as RequestInit | undefined)?.method === "PATCH",
      ),
    ).toBe(false);

    await user.click(screen.getByRole("button", { name: "Confirm change" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/admin/data/tables/inventory_items/rows/item-1",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
  });
});
