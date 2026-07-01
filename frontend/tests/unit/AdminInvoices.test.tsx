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
  amount_total: "100.00",
  currency: "usd",
  memo: "first invoice",
  due_date: "2026-07-01",
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

  it("creating an invoice sends customer_id/memo as query params and a bare line-items array body", async () => {
    // This is exactly the shape bug this test exists to guard against
    // reintroducing: api/invoices.py's create() route takes customer_id
    // and memo as scalar (query param) arguments and line_items as the
    // ONE body-eligible param, so the whole request body is the bare
    // array, not an envelope object -- see api/invoices.ts's
    // createInvoice doc comment.
    // URL-routed, not a positional mockResolvedValueOnce queue -- the
    // customers list query fires as soon as the form opens (before any
    // field is filled in), which would otherwise consume a queue slot
    // meant for the create-invoice call and crash the form (a real
    // failure this test caught: customersQuery.data ended up being a
    // single invoice object, not an array, from exactly this ordering
    // mismatch).
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/admin/customers") {
        return Promise.resolve(
          jsonResponse([{ id: "cust-123", email: "customer@example.com" }]),
        );
      }
      if (url.startsWith("/api/admin/invoices?")) {
        return Promise.resolve(jsonResponse({ id: "inv-new" }));
      }
      return Promise.resolve(jsonResponse([draftInvoice]));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "New invoice" }));
    await user.selectOptions(
      await screen.findByLabelText("Bill to"),
      "customer@example.com",
    );
    await user.type(screen.getByLabelText("Description"), "Consulting");
    await user.clear(screen.getByLabelText("Qty"));
    await user.type(screen.getByLabelText("Qty"), "2");
    await user.type(screen.getByLabelText("Unit price"), "50.00");
    await user.type(screen.getByLabelText("Memo (optional)"), "Test memo");

    await user.click(screen.getByRole("button", { name: "Create invoice" }));

    await waitFor(() => {
      const createCall = fetchMock.mock.calls.find(([url]) =>
        String(url).startsWith("/api/admin/invoices?"),
      ) as [string, RequestInit] | undefined;
      expect(createCall).toBeDefined();
      const [url, init] = createCall!;
      expect(url).toBe("/api/admin/invoices?customer_id=cust-123&memo=Test+memo");
      expect(JSON.parse(String(init.body))).toEqual([
        { description: "Consulting", quantity: "2", unit_price: "50" },
      ]);
    });
  });
});
