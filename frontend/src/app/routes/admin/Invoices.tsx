import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listAdminInvoices, sendInvoice, voidInvoice } from "../../../api/invoices";
import { BUTTON_CLASS } from "../../../styles/a11y";

// TODO(logan): create-invoice form (React Hook Form + zod) is still missing --
// this wires up list/send/void against real endpoints first since that's the
// higher-value data-flow path to prove out.
export function AdminInvoices() {
  const queryClient = useQueryClient();
  const {
    data: invoices,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["admin", "invoices"],
    queryFn: listAdminInvoices,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "invoices"] });
  const sendMutation = useMutation({ mutationFn: sendInvoice, onSuccess: invalidate });
  const voidMutation = useMutation({ mutationFn: voidInvoice, onSuccess: invalidate });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Invoices (admin)</h1>
      {isLoading && <p className="text-base text-fg-muted">Loading...</p>}
      {isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load invoices.
        </p>
      )}
      {invoices && (
        // Horizontal scroll wrapper, not a fixed-width table, so this stays
        // usable on a 375px-wide mobile viewport instead of overflowing or
        // forcing a tiny unreadable font.
        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[640px] text-base text-fg-primary">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="p-2">Status</th>
                <th className="p-2">Amount</th>
                <th className="p-2">Due</th>
                <th className="p-2">Memo</th>
                <th className="p-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <tr key={invoice.id} className="border-b border-border">
                  <td className="p-2">{invoice.status}</td>
                  <td className="p-2">
                    {invoice.amountTotal} {invoice.currency}
                  </td>
                  <td className="p-2">{invoice.dueDate ?? "-"}</td>
                  <td className="p-2">{invoice.memo ?? "-"}</td>
                  <td className="flex flex-wrap gap-2 p-2">
                    <button
                      type="button"
                      disabled={invoice.status !== "draft"}
                      onClick={() => sendMutation.mutate(invoice.id)}
                      aria-label={`Send invoice ${invoice.id}`}
                      className={BUTTON_CLASS}
                    >
                      Send
                    </button>
                    <button
                      type="button"
                      disabled={invoice.status === "void"}
                      onClick={() => voidMutation.mutate(invoice.id)}
                      aria-label={`Void invoice ${invoice.id}`}
                      className={BUTTON_CLASS}
                    >
                      Void
                    </button>
                    {/* Same plain-<a>-not-fetch approach as
                        customer/Invoices.tsx -- see that file's identical
                        comment. Admins can preview a draft's PDF too (the
                        backend route has no status restriction), unlike
                        Pay/the customer view. */}
                    <a
                      href={`/api/admin/invoices/${invoice.id}/pdf`}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`Download PDF for invoice ${invoice.id}`}
                      className={BUTTON_CLASS}
                    >
                      PDF
                    </a>
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
