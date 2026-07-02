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

**Portal**: `/portal` (linked from the top nav as "portal" once logged
in) is your account home base, linking to your invoices.

**Email notifications**: if the site operator has SMTP configured,
you'll get an email when an invoice is sent to you and when a payment
you made is recorded. Every email has an "Unsubscribe" link in the
footer -- clicking it opts you out immediately, no login required.

## As the admin

Log in with your admin account at `/login`. The nav shows "portal" --
that's `/admin`, a landing page linking invoicing, budget, and
inventory.

**Invoicing** (`/admin/invoices`):

- **Create** -- the "New invoice" button opens a form: pick a customer
  (by email, from the customer list), add one or more line items
  (description/quantity/unit price), an optional memo, and submit. The
  invoice starts as `draft`.
- **Invoice lifecycle**: `draft -> sent -> paid` (or `void` at any
  point after `sent`, `overdue` if the due date passes unpaid). Line
  items are frozen once an invoice is sent, so what the customer sees
  never changes underneath them.
- **Send** -- moves a draft to `sent`, making it visible/payable to the
  customer. If SMTP is configured, this also emails the customer.
- **Void** -- cancels a sent/overdue invoice.
- **Record payment** -- for any `sent`/`overdue` invoice, records a
  payment that happened outside the system: pick Zelle, PayPal (sent
  directly), in person, or other; enter the amount and an optional note
  (a Zelle confirmation number, etc.). Once recorded payments cover the
  full amount, the invoice flips to `paid` automatically (and emails
  the customer, if SMTP is configured). A partial payment stays
  recorded but leaves the invoice payable for the rest.
- **PDF** -- same download as the customer sees, but available for a
  draft invoice too (a preview before sending).

**Budget and inventory** (`/admin/budget`, `/admin/inventory`, linked
from the `/admin` portal page): expense-ledger and personal-inventory
tracking respectively. See [design/05-budget.md](design/05-budget.md)
and [design/06-inventory.md](design/06-inventory.md) for what each
supports today; both also have known-incomplete pieces (evidence
upload, location/tag filters) flagged in their own route files' `TODO`
comments.

**Mileage, receipts, and documents/CAD tracking** -- backend API only
right now, no frontend page yet (`POST/GET /api/admin/mileage`,
`/api/admin/receipts`, `/api/admin/documents`). See
[design/14-mileage-receipts-documents.md](design/14-mileage-receipts-documents.md)
for the full request shapes -- this API surface was built specifically
to be the stable contract a future native Android app (for on-the-go
mileage logging and receipt-photo capture) will talk to.

## Email notifications (both roles)

See [secrets.md](secrets.md)'s `SMTP_*`/`MAILING_ADDRESS` section for
how the site operator turns this on. When configured:

- Customers get an email when an invoice is sent to them and when a
  payment is recorded against one of their invoices.
- Every email is sent as proper `multipart/alternative` (HTML + plain
  text), with `List-Unsubscribe`/`List-Unsubscribe-Post` headers so
  mail clients can offer one-click unsubscribe, and a footer with the
  operator's mailing address (CAN-SPAM compliance).
- Unsubscribing (either via the in-email link or a mail client's
  one-click button) sets a permanent opt-out flag on that account --
  no further notification emails go out until an admin/database change
  reverses it.
