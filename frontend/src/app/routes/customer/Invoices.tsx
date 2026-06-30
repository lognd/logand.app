// TODO(logan): list only the logged-in customer's own invoices
// (GET /api/invoices, server already scopes by session -- never trust a
// client-supplied customer_id). Links to Pay.tsx for unpaid ones.
export function CustomerInvoices() {
  return (
    <main>
      <h1>Your invoices</h1>
    </main>
  );
}
