import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminInvoices } from "../../src/app/routes/admin/Invoices";
import type { Invoice } from "../../src/api/invoices";

// Integration-layer test per docs/design/12: real api/invoices.ts module,
// only the underlying fetch() is mocked -- proves the component, the
// TanStack Query wiring, and the API module's request shaping all work
// together, not just that each piece works in isolation.

const draftInvoice: Invoice = {
  id: "inv-1",
  status: "draft",
  amountTotal: "100.00",
  currency: "usd",
  memo: "first invoice",
  dueDate: "2026-07-01",
};

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
      <AdminInvoices />
    </QueryClientProvider>,
  );
}

describe("AdminInvoices (integration)", () => {
  beforeEach(() => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, assign: vi.fn() },
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders a loading state, then real invoice data from the API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([draftInvoice]));
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(await screen.findByText("draft")).toBeInTheDocument();
    expect(screen.getByText(/100.00 usd/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/invoices",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("clicking Send calls POST /send through the real api module and refreshes the list", async () => {
    const sentInvoice: Invoice = { ...draftInvoice, status: "sent" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([draftInvoice]))
      .mockResolvedValueOnce(jsonResponse(sentInvoice))
      .mockResolvedValueOnce(jsonResponse([sentInvoice]));
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    const sendButton = await screen.findByRole("button", {
      name: `Send invoice ${draftInvoice.id}`,
    });
    await user.click(sendButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/admin/invoices/${draftInvoice.id}/send`,
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(await screen.findByText("sent")).toBeInTheDocument();
  });
});
