# Using the site

Audience: anyone using the deployed site itself -- a customer paying an
invoice, or the admin (Logan) running things day to day. For how the
underlying features are built, see [design/04-invoices.md](design/04-invoices.md),
[05-budget.md](design/05-budget.md), [06-inventory.md](design/06-inventory.md).

## As a visitor (no account)

The public pages -- landing (`/`), projects (`/projects`), contact
(`/contact`) -- need no login. The animated ASCII background (donut,
cube, globe, or a matrix-rain effect) is picked at random on each visit;
pick a specific one yourself, or click-and-drag to spin/nudge it. The
same background embeds in the "logand.app" project card on `/projects`
as a live preview of this very site.

## As a customer

**Register**: `/register`, email + password (8+ characters). This logs
you in immediately -- self-registration always creates a customer
account (there's no way to become an admin through this form).

**View and pay invoices**: `/invoices` lists everything sent to your
account -- status, amount, due date. For anything `sent` or `overdue`:

- **Pay with card** -- starts a real Stripe payment.
- **Pay with PayPal** -- only shown if the site operator has PayPal
  configured; redirects to PayPal's own approval page and comes back
  here automatically once you approve it.
- **Prefer Zelle, a direct PayPal transfer, or paying in person?** --
  contact the site operator directly; they'll record it once received
  and your invoice will show as paid.

**Download a PDF**: every invoice has a "Download PDF" link -- a real,
printable invoice with an itemized breakdown, due date, and (while
still payable) a clickable "pay online" link.

## As the admin

Log in with your admin account at `/login`. The nav shows "invoicing"
instead of "my invoices" -- that's `/admin/invoices`.

**Invoice lifecycle**: `draft -> sent -> paid` (or `void` at any point
after `sent`, `overdue` if the due date passes unpaid). Line items are
frozen once an invoice is sent, so what the customer sees never changes
underneath them.

- **Send** -- moves a draft to `sent`, making it visible/payable to the
  customer.
- **Void** -- cancels a sent/overdue invoice.
- **Record payment** -- for any `sent`/`overdue` invoice, records a
  payment that happened outside the system: pick Zelle, PayPal (sent
  directly), in person, or other; enter the amount and an optional note
  (a Zelle confirmation number, etc.). Once recorded payments cover the
  full amount, the invoice flips to `paid` automatically. A partial
  payment stays recorded but leaves the invoice payable for the rest.
- **PDF** -- same download as the customer sees, but available for a
  draft invoice too (a preview before sending).

**Known gap**: there is currently no UI to *create* a new invoice from
scratch (the form doesn't exist yet -- see the `TODO` at the top of
`frontend/src/app/routes/admin/Invoices.tsx`). Creating one today
requires calling `POST /api/admin/invoices` directly (see
[design/04-invoices.md](design/04-invoices.md) for the exact request
shape) until that form is built.

**Budget and inventory** (`/admin/budget`, `/admin/inventory`, not
linked from the top nav -- reachable directly by URL): expense-ledger
and personal-inventory tracking respectively. See
[design/05-budget.md](design/05-budget.md) and
[design/06-inventory.md](design/06-inventory.md) for what each supports
today; both also have known-incomplete pieces (evidence upload,
location/tag filters) flagged in their own route files' `TODO`
comments.
