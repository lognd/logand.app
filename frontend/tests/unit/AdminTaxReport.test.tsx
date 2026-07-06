import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { AdminTaxReport } from "../../src/app/routes/admin/TaxReport";
import type { TaxReport } from "../../src/api/invoices";
import type { StripeTaxReconcile } from "../../src/api/tax";

// Integration-layer test (docs/design/12): real api/invoices.ts, only fetch()
// mocked -- proves the page, TanStack Query wiring, and the tax-report request
// shaping work together.

const report: TaxReport = {
  from_date: "2026-01-01",
  to_date: "2026-07-05",
  currency: "usd",
  invoice_count: 3,
  total_sales: "1000.00",
  total_tax_collected: "72.50",
  filing_jurisdictions: ["US-TN", "US-customs"],
  by_jurisdiction: [
    {
      jurisdiction: "US-TN",
      tax_type: "sales",
      taxable_base: "800.00",
      tax_collected: "56.00",
    },
    {
      jurisdiction: "US-customs",
      tax_type: "import_duty",
      taxable_base: "825.00",
      tax_collected: "16.50",
    },
  ],
  by_category: [
    { category: "tangible-goods", gross: "800.00", taxable_gross: "800.00" },
    { category: "service", gross: "200.00", taxable_gross: "0.00" },
  ],
};

const stripeReconcile: StripeTaxReconcile = {
  total_tax_collected: "40.00",
  by_jurisdiction: { "US-TN": "40.00" },
  transaction_count: 2,
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
      <AdminTaxReport />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

it("requests the tax-report endpoint with the date range and renders it", async () => {
  const urlsCalled: string[] = [];
  const fetchMock = vi.fn((input: unknown) => {
    const calledUrl = String(input);
    urlsCalled.push(calledUrl);
    if (calledUrl.includes("/api/admin/tax/stripe-reconcile")) {
      return Promise.resolve(jsonResponse(stripeReconcile));
    }
    return Promise.resolve(jsonResponse(report));
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage();

  // Summary tiles + collected total from the report.
  expect(await screen.findByText("72.50")).toBeInTheDocument();
  expect(screen.getByText("1000.00")).toBeInTheDocument();

  // Filing jurisdictions and per-jurisdiction rows.
  expect(screen.getAllByText("US-TN").length).toBeGreaterThan(0);
  expect(screen.getByText("import_duty")).toBeInTheDocument();
  expect(screen.getByText("56.00")).toBeInTheDocument();

  // Category breakdown.
  expect(screen.getByText("tangible-goods")).toBeInTheDocument();

  // The request hit the tax-report endpoint with the date params.
  const taxReportUrl = urlsCalled.find((u) => u.includes("/api/admin/invoices/tax-report"));
  expect(taxReportUrl).toBeDefined();
  expect(taxReportUrl).toContain("from_date=");
  expect(taxReportUrl).toContain("to_date=");

  // Stripe's own reconciliation figures are also queried and rendered.
  expect((await screen.findAllByText("40.00")).length).toBeGreaterThan(0);
  expect(
    urlsCalled.some((u) => u.includes("/api/admin/tax/stripe-reconcile")),
  ).toBe(true);
});
