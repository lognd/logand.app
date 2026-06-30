import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listAdminInvoices, sendInvoice, voidInvoice } from "../../../api/invoices";

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
    <main>
      <h1>Invoices (admin)</h1>
      {isLoading && <p>Loading...</p>}
      {isError && <p role="alert">Failed to load invoices.</p>}
      {invoices && (
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Amount</th>
              <th>Due</th>
              <th>Memo</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((invoice) => (
              <tr key={invoice.id}>
                <td>{invoice.status}</td>
                <td>
                  {invoice.amountTotal} {invoice.currency}
                </td>
                <td>{invoice.dueDate ?? "-"}</td>
                <td>{invoice.memo ?? "-"}</td>
                <td>
                  <button
                    type="button"
                    disabled={invoice.status !== "draft"}
                    onClick={() => sendMutation.mutate(invoice.id)}
                  >
                    Send
                  </button>
                  <button
                    type="button"
                    disabled={invoice.status === "void"}
                    onClick={() => voidMutation.mutate(invoice.id)}
                  >
                    Void
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
