import { useQuery } from "@tanstack/react-query";
import { getInvoiceStats } from "../../../api/invoices";

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  sent: "Sent",
  paid: "Paid",
  overdue: "Overdue",
  void: "Void",
  refunded: "Refunded",
};

const METHOD_LABEL: Record<string, string> = {
  stripe: "Stripe",
  paypal: "PayPal",
  zelle: "Zelle",
  in_person: "In person",
  other: "Other",
};

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border p-4">
      <p className="text-sm text-fg-muted">{label}</p>
      <p className="text-2xl text-fg-primary">{value}</p>
    </div>
  );
}

// Read-only breakdown of invoices/payments/refunds/disputes -- everything
// here is computed fresh on the server from real rows (domain/invoices/
// stats.py::get_invoice_stats), never cached/denormalized, so it can't
// drift out of sync with what AdminInvoices.tsx itself shows.
export function AdminStats() {
  const statsQuery = useQuery({
    queryKey: ["admin", "invoices", "stats"],
    queryFn: getInvoiceStats,
  });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Invoice stats (admin)</h1>

      {statsQuery.isLoading && <p className="text-base text-fg-muted">Loading...</p>}
      {statsQuery.isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load stats.
        </p>
      )}

      {statsQuery.data && (
        <>
          <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatTile label="Total collected" value={statsQuery.data.total_collected} />
            <StatTile label="Total refunded" value={statsQuery.data.total_refunded} />
            <StatTile label="Net collected" value={statsQuery.data.net_collected} />
            <StatTile label="Outstanding" value={statsQuery.data.outstanding} />
          </div>

          {statsQuery.data.open_disputes > 0 && (
            <p role="alert" className="mb-8 text-base text-accent-red">
              {statsQuery.data.open_disputes} open Stripe dispute
              {statsQuery.data.open_disputes === 1 ? "" : "s"} need attention.
            </p>
          )}

          <h2 className="mb-2 text-lg text-fg-primary">Invoices by status</h2>
          <div className="mb-8 w-full overflow-x-auto">
            <table className="w-full min-w-[420px] text-base text-fg-primary">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="p-2">Status</th>
                  <th className="p-2">Count</th>
                  <th className="p-2">Amount</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(statsQuery.data.by_status).map(([status, breakdown]) => (
                  <tr key={status} className="border-b border-border">
                    <td className="p-2">{STATUS_LABEL[status] ?? status}</td>
                    <td className="p-2">{breakdown.count}</td>
                    <td className="p-2">{breakdown.amount_total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 className="mb-2 text-lg text-fg-primary">Payments by method</h2>
          <div className="mb-8 w-full overflow-x-auto">
            <table className="w-full min-w-[420px] text-base text-fg-primary">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="p-2">Method</th>
                  <th className="p-2">Count</th>
                  <th className="p-2">Amount</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(statsQuery.data.by_payment_method).map(
                  ([method, breakdown]) => (
                    <tr key={method} className="border-b border-border">
                      <td className="p-2">{METHOD_LABEL[method] ?? method}</td>
                      <td className="p-2">{breakdown.count}</td>
                      <td className="p-2">{breakdown.amount}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>

          <h2 className="mb-2 text-lg text-fg-primary">Disputes</h2>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-base">
            <dt className="text-fg-muted">Needs response</dt>
            <dd className="text-fg-primary">{statsQuery.data.disputes.needs_response}</dd>
            <dt className="text-fg-muted">Under review</dt>
            <dd className="text-fg-primary">{statsQuery.data.disputes.under_review}</dd>
            <dt className="text-fg-muted">Won</dt>
            <dd className="text-fg-primary">{statsQuery.data.disputes.won}</dd>
            <dt className="text-fg-muted">Lost</dt>
            <dd className="text-fg-primary">{statsQuery.data.disputes.lost}</dd>
          </dl>
        </>
      )}
    </main>
  );
}
