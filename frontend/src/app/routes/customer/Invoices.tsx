import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listInvoices } from "../../../api/invoices";

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
    <main>
      <h1>Your invoices</h1>
      {isLoading && <p>Loading...</p>}
      {isError && <p role="alert">Failed to load invoices.</p>}
      {invoices && (
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Amount</th>
              <th>Due</th>
              <th>Action</th>
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
                <td>
                  {invoice.status === "sent" || invoice.status === "overdue" ? (
                    <Link to={`/invoices/${invoice.id}/pay`}>Pay now</Link>
                  ) : (
                    "-"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
