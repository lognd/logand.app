import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminInvoices } from "../../src/app/routes/admin/Invoices";
import { AdminStats } from "../../src/app/routes/admin/Stats";
import type { Invoice, InvoiceDetail, InvoiceStats } from "../../src/api/invoices";

// Same "real api module, only fetch() mocked" integration-layer
// convention as AdminInvoices.test.tsx -- proves the refund/stats UI
// added alongside domain/invoices/refunds.py and stats.py actually
// wires up to those routes with the shapes they really return.

const paidInvoice: Invoice = {
  id: "inv-1",
  status: "paid",
  amount_total: "100.00",
  currency: "usd",
  memo: "widget order",
  due_date: "2026-07-01",
  paid_at: "2026-07-02T00:00:00Z",
};

const paidInvoiceDetail: InvoiceDetail = {
  ...paidInvoice,
  line_items: [],
  payments: [
    {
      id: "pay-1",
      method: "zelle",
      amount: "100.00",
      status: "succeeded",
      transaction_id: null,
      note: "Zelle #123",
      recorded_by: "admin-1",
      dispute_status: null,
      refunds: [],
    },
  ],
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("AdminInvoices refund UI (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a payment's dispute status and lets an admin issue a refund", async () => {
    const fetchMock = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/admin/invoices")
        return Promise.resolve(jsonResponse([paidInvoice]));
      if (path === "/api/admin/invoices/inv-1") {
        return Promise.resolve(jsonResponse(paidInvoiceDetail));
      }
      if (path === "/api/admin/invoices/inv-1/payments/pay-1/refund") {
        return Promise.resolve(jsonResponse({ id: "refund-1" }));
      }
      throw new Error(`unexpected fetch: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage(<AdminInvoices />);

    await screen.findByText("paid");
    await user.click(screen.getByRole("button", { name: "View payments" }));

    await screen.findByText(/zelle -- 100.00 \(succeeded\)/);

    await user.click(screen.getByRole("button", { name: "Refund payment pay-1" }));
    await user.type(screen.getByLabelText(/Reason \(optional\)/), "duplicate charge");
    await user.click(screen.getByRole("button", { name: "Confirm refund" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([path]) => path === "/api/admin/invoices/inv-1/payments/pay-1/refund",
      );
      expect(call).toBeDefined();
      const [, options] = call!;
      expect(options).toEqual(expect.objectContaining({ method: "POST" }));
      const body = JSON.parse((options as RequestInit).body as string);
      // client_request_id is generated with crypto.randomUUID() when the
      // refund action starts (H1 fix) -- assert shape, not an exact value.
      expect(body).toEqual({
        payment_id: "pay-1",
        amount: undefined,
        reason: "duplicate charge",
        client_request_id: expect.stringMatching(
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
        ),
      });
    });
  });

  it("renders a dispute badge when a payment has an open Stripe dispute", async () => {
    const disputedDetail: InvoiceDetail = {
      ...paidInvoiceDetail,
      payments: [
        {
          ...paidInvoiceDetail.payments[0],
          method: "stripe",
          dispute_status: "needs_response",
        },
      ],
    };
    const fetchMock = vi.fn().mockImplementation((path: string) => {
      if (path === "/api/admin/invoices")
        return Promise.resolve(jsonResponse([paidInvoice]));
      if (path === "/api/admin/invoices/inv-1") {
        return Promise.resolve(jsonResponse(disputedDetail));
      }
      throw new Error(`unexpected fetch: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage(<AdminInvoices />);

    await screen.findByText("paid");
    await user.click(screen.getByRole("button", { name: "View payments" }));

    expect(await screen.findByText("Dispute: needs response")).toBeInTheDocument();
  });
});

describe("AdminStats (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the real stats breakdown from the API", async () => {
    const stats: InvoiceStats = {
      by_status: {
        draft: { count: 0, amount_total: "0.00" },
        sent: { count: 1, amount_total: "25.00" },
        paid: { count: 2, amount_total: "150.00" },
        overdue: { count: 0, amount_total: "0.00" },
        void: { count: 0, amount_total: "0.00" },
        refunded: { count: 1, amount_total: "40.00" },
      },
      total_collected: "190.00",
      total_refunded: "40.00",
      net_collected: "150.00",
      outstanding: "25.00",
      by_payment_method: { zelle: { count: 2, amount: "150.00" } },
      open_disputes: 1,
      disputes: { needs_response: 1, under_review: 0, won: 0, lost: 0 },
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stats));
    vi.stubGlobal("fetch", fetchMock);

    renderPage(<AdminStats />);

    expect(await screen.findByText("190.00")).toBeInTheDocument();
    expect(screen.getAllByText("150.00").length).toBeGreaterThan(0);
    expect(screen.getByText(/1 open Stripe dispute/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/invoices/stats",
      expect.objectContaining({ method: "GET" }),
    );
  });
});
