// TODO(logan): Stripe Elements/Checkout flow against the client_secret
// returned by POST /api/invoices/:id/pay, see docs/design/04-invoices.md.
// Rate-limited 20/min server-side -- surface RateLimitedError nicely.
export function CustomerPay() {
  return (
    <main>
      <h1>Pay invoice</h1>
    </main>
  );
}
