import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listInvoices, openInvoicePdf } from "../../../api/invoices";
import { BUTTON_CLASS, LINK_CLASS } from "../../../styles/a11y";

export function CustomerInvoices() {
  const {
    data: invoices,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["invoices"],
    queryFn: listInvoices,
  });

  // A single mutation instance, keyed by `variables` (the invoice id) to
  // know which row is currently loading/erred -- realistically only one
  // PDF is being opened at a time, so this is simpler than per-row state
  // for the same practical behavior (matches AdminInvoices.tsx's
  // send/void mutations).
  const pdfMutation = useMutation({
    mutationFn: (id: string) => openInvoicePdf(`/api/invoices/${id}/pdf`),
  });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Your invoices</h1>
      {isLoading && <p className="text-base text-fg-muted">Loading...</p>}
      {isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load invoices.
        </p>
      )}
      {invoices && (
        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[480px] text-base text-fg-primary">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="p-2">Status</th>
                <th className="p-2">Amount</th>
                <th className="p-2">Due</th>
                <th className="p-2">Paid</th>
                <th className="p-2">Action</th>
                <th className="p-2">PDF</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <tr key={invoice.id} className="border-b border-border">
                  <td className="p-2">{invoice.status}</td>
                  <td className="p-2">
                    {invoice.amount_total} {invoice.currency}
                  </td>
                  <td className="p-2">{invoice.due_date ?? "-"}</td>
                  <td className="p-2">
                    {invoice.paid_at ? new Date(invoice.paid_at).toLocaleDateString() : "-"}
                  </td>
                  <td className="p-2">
                    {invoice.status === "sent" || invoice.status === "overdue" ? (
                      <Link
                        to={`/invoices/${invoice.id}/pay`}
                        className={LINK_CLASS}
                        aria-label={`Pay invoice ${invoice.id}`}
                      >
                        Pay now
                      </Link>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td className="p-2">
                    {/* A real fetch+blob open, not a plain <a href> -- see
                        openInvoicePdf's own doc comment for why: a plain
                        link against a failing endpoint just opened a
                        blank/raw-error tab with no usable feedback. */}
                    <button
                      type="button"
                      onClick={() => pdfMutation.mutate(invoice.id)}
                      disabled={pdfMutation.isPending && pdfMutation.variables === invoice.id}
                      className={BUTTON_CLASS}
                      aria-label={`Download PDF for invoice ${invoice.id}`}
                    >
                      {pdfMutation.isPending && pdfMutation.variables === invoice.id
                        ? "Opening..."
                        : "Download PDF"}
                    </button>
                    {pdfMutation.isError && pdfMutation.variables === invoice.id && (
                      <p role="alert" className="mt-1 text-sm text-accent-red">
                        {pdfMutation.error instanceof Error
                          ? pdfMutation.error.message
                          : "Could not open the PDF."}
                      </p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
