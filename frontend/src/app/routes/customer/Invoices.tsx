import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listInvoices } from "../../../api/invoices";
import { LINK_CLASS } from "../../../styles/a11y";

export function CustomerInvoices() {
  const {
    data: invoices,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["invoices"],
    queryFn: listInvoices,
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
                <th className="p-2">Action</th>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
