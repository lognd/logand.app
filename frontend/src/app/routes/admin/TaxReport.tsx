import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getTaxReport } from "../../../api/invoices";
import { getStripeReconcile } from "../../../api/tax";
import { BUTTON_CLASS } from "../../../styles/a11y";

// Default the range to the current calendar year -- the usual filing window.
function yearStart(): string {
  return `${new Date().getFullYear()}-01-01`;
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border p-4">
      <p className="text-sm text-fg-muted">{label}</p>
      <p className="text-2xl text-fg-primary">{value}</p>
    </div>
  );
}

// Read-only tax-filing breakdown over a date range: what was sold of each tax
// category, tax collected per jurisdiction + type, and which jurisdictions
// have a filing obligation. Everything is computed fresh on the server from
// real invoice rows (domain/invoices/tax/report.py), the same figures the
// invoices show -- safe to hand to an accountant or feed to Claude when
// filling out forms. See docs/design/16-sales-tax.md.
export function AdminTaxReport() {
  // The applied range that drives the query; the inputs below stage edits
  // until "Run report" so a half-typed date doesn't fire a request.
  const [range, setRange] = useState({ from: yearStart(), to: today() });
  const [draft, setDraft] = useState(range);

  const reportQuery = useQuery({
    queryKey: ["admin", "invoices", "tax-report", range.from, range.to],
    queryFn: () => getTaxReport(range.from, range.to),
    enabled: !!range.from && !!range.to,
  });

  const report = reportQuery.data;

  const stripeReconcileQuery = useQuery({
    queryKey: ["admin", "tax", "stripe-reconcile", range.from, range.to],
    queryFn: () => getStripeReconcile(range.from, range.to),
    enabled: !!range.from && !!range.to,
  });

  const stripeReconcile = stripeReconcileQuery.data;

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-2 text-2xl text-fg-primary">Tax report (admin)</h1>
      <p className="mb-6 text-base text-fg-muted">
        Sales and tax collected over a date range, broken down for filing. Both
        the From and To dates are inclusive -- the whole To day is covered.
        Figures are computed from real invoices and reconcile exactly with what
        customers were charged. This is an aid for filing, not tax advice.
      </p>

      <form
        className="mb-8 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setRange(draft);
        }}
      >
        <label className="flex flex-col text-sm text-fg-muted">
          From
          <input
            type="date"
            value={draft.from}
            max={draft.to}
            onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))}
            className="mt-1 rounded border border-border bg-bg-secondary p-2 text-base text-fg-primary"
          />
        </label>
        <label className="flex flex-col text-sm text-fg-muted">
          To
          <input
            type="date"
            value={draft.to}
            min={draft.from}
            onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))}
            className="mt-1 rounded border border-border bg-bg-secondary p-2 text-base text-fg-primary"
          />
        </label>
        <button type="submit" className={BUTTON_CLASS}>
          Run report
        </button>
      </form>

      {reportQuery.isLoading && (
        <p className="text-base text-fg-muted">Loading...</p>
      )}
      {reportQuery.isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load the tax report.
        </p>
      )}

      {report && (
        <>
          <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3">
            <StatTile label="Invoices" value={String(report.invoice_count)} />
            <StatTile label="Total sales" value={report.total_sales} />
            <StatTile label="Tax collected" value={report.total_tax_collected} />
          </div>

          <div className="mb-8 rounded border border-border p-4">
            <p className="text-base text-fg-primary">Jurisdictions to file for</p>
            {report.filing_jurisdictions.length === 0 ? (
              <p className="mt-2 text-base text-fg-muted">
                No tax was collected in this range -- nothing to file.
              </p>
            ) : (
              <p className="mt-2 text-base text-fg-primary">
                {report.filing_jurisdictions.map((j) => (
                  <span
                    key={j}
                    className="mr-2 inline-block rounded bg-bg-secondary px-2 py-1 font-mono text-sm"
                  >
                    {j}
                  </span>
                ))}
              </p>
            )}
          </div>

          <h2 className="mb-2 text-lg text-fg-primary">Tax collected by jurisdiction</h2>
          <div className="mb-8 w-full overflow-x-auto">
            <table className="w-full min-w-[520px] text-base text-fg-primary">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="p-2">Jurisdiction</th>
                  <th className="p-2">Tax type</th>
                  <th className="p-2">Taxable base</th>
                  <th className="p-2">Tax collected</th>
                </tr>
              </thead>
              <tbody>
                {report.by_jurisdiction.length === 0 ? (
                  <tr>
                    <td className="p-2 text-fg-muted" colSpan={4}>
                      No tax collected in this range.
                    </td>
                  </tr>
                ) : (
                  report.by_jurisdiction.map((r) => (
                    <tr key={`${r.jurisdiction}-${r.tax_type}`} className="border-b border-border">
                      <td className="p-2 font-mono">{r.jurisdiction}</td>
                      <td className="p-2">{r.tax_type}</td>
                      <td className="p-2 tabular-nums">{r.taxable_base}</td>
                      <td className="p-2 tabular-nums">{r.tax_collected}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <h2 className="mb-2 text-lg text-fg-primary">Sales by tax category</h2>
          <div className="mb-8 w-full overflow-x-auto">
            <table className="w-full min-w-[520px] text-base text-fg-primary">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="p-2">Category</th>
                  <th className="p-2">Gross sold</th>
                  <th className="p-2">Taxable portion</th>
                </tr>
              </thead>
              <tbody>
                {report.by_category.length === 0 ? (
                  <tr>
                    <td className="p-2 text-fg-muted" colSpan={3}>
                      No sales in this range.
                    </td>
                  </tr>
                ) : (
                  report.by_category.map((r) => (
                    <tr key={r.category} className="border-b border-border">
                      <td className="p-2 font-mono">{r.category}</td>
                      <td className="p-2 tabular-nums">{r.gross}</td>
                      <td className="p-2 tabular-nums">{r.taxable_gross}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <h2 className="mb-2 text-lg text-fg-primary">
            Stripe-collected tax (for comparison)
          </h2>
          <p className="mb-2 text-sm text-fg-muted">
            This is Stripe's own recorded figure for cross-checking against the
            report above -- it only covers payments processed through Stripe,
            not Zelle/PayPal/in-person/other manual payments.
          </p>
          {stripeReconcileQuery.isLoading && (
            <p className="text-base text-fg-muted">Loading...</p>
          )}
          {stripeReconcileQuery.isError && (
            <p role="alert" className="text-base text-accent-red">
              Failed to load Stripe's reconciliation figures.
            </p>
          )}
          {stripeReconcile && (
            <div className="mb-8">
              <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
                <StatTile
                  label="Stripe tax collected"
                  value={stripeReconcile.total_tax_collected}
                />
                <StatTile
                  label="Stripe transactions"
                  value={String(stripeReconcile.transaction_count)}
                />
              </div>
              <div className="w-full overflow-x-auto">
                <table className="w-full min-w-[420px] text-base text-fg-primary">
                  <thead>
                    <tr className="border-b border-border text-left">
                      <th className="p-2">Jurisdiction</th>
                      <th className="p-2">Tax collected</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(stripeReconcile.by_jurisdiction).length === 0 ? (
                      <tr>
                        <td className="p-2 text-fg-muted" colSpan={2}>
                          No Stripe-collected tax in this range.
                        </td>
                      </tr>
                    ) : (
                      Object.entries(stripeReconcile.by_jurisdiction).map(
                        ([jurisdiction, amount]) => (
                          <tr key={jurisdiction} className="border-b border-border">
                            <td className="p-2 font-mono">{jurisdiction}</td>
                            <td className="p-2 tabular-nums">{amount}</td>
                          </tr>
                        ),
                      )
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}
