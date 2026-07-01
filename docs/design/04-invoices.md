# 04 -- Invoices

Audience: anyone building invoice endpoints (admin or customer-facing)
or the payment integration. Read [00-overview.md](00-overview.md),
[02-auth-and-security.md](02-auth-and-security.md), and the `users`/
`sessions` tables in [03-database.md](03-database.md) first.

> **Post-design update**: this doc predates several things that now
> exist in the real implementation -- multi-method payments (PayPal,
> Zelle, in-person), professional PDF invoice generation, and the
> atomicity fixes described below. The schema/endpoints sections have
> been updated to match; see [docs/usage.md](../usage.md) for how a
> customer/admin actually uses any of this day to day.

## Decision: payment processor is Stripe (primary), with alternatives

Card data must never touch our server or database -- that's a PCI-DSS
liability we don't need to take on. Stripe Checkout / Payment Intents
handles card capture entirely on Stripe's hosted surface; our backend
only ever sees a `payment_intent_id` and webhook events. This is a
professional default, not requiring a human decision: building custom
card handling would mean self-attesting PCI compliance, which is the
wrong tradeoff for a personal/small-business site.

`PAYMENT_PROCESSOR_SECRET` env var (see [02](02-auth-and-security.md))
is the Stripe secret key; webhook signature verification uses a second
env var `STRIPE_WEBHOOK_SECRET`. Both placeholders only in examples.

Beyond Stripe, a customer can also pay via:

- **PayPal** -- a real PayPal Orders API v2 integration
  (`domain/payments/providers/paypal.py`), fully optional: if
  `PAYPAL_CLIENT_ID`/`PAYPAL_CLIENT_SECRET` aren't set,
  `GET /api/invoices/payment-methods` reports it unavailable and
  `POST /{id}/pay/paypal` returns a real `503` rather than a confusing
  error -- the frontend falls back to showing "contact us to pay via
  Zelle/PayPal/in person" messaging instead of a broken button.
- **Manually-recorded payments** (Zelle, in person, or a PayPal payment
  sent customer-to-admin directly rather than through the API) -- an
  admin records these via `POST /api/admin/invoices/{id}/payments/manual`.
  No provider API call at all; this is bookkeeping for money that moved
  outside the system, not payment processing.

## Concurrency / atomicity

Every endpoint that reads an invoice's status/amount and then acts on
it (`/pay`, `/pay/paypal`, `/pay/paypal/capture`,
`/payments/manual`, `/send`, `/void`) takes a row-level lock
(`SELECT ... FOR UPDATE`, see `domain/invoices/service.py`'s
`lock_invoice_for_update`) before reading, so two concurrent requests
against the *same* invoice (a double-clicked Pay button, two open
tabs, a retried webhook) serialize instead of racing. This does not
lock other invoices -- unrelated payments never contend with each
other. `pay_invoice` additionally reuses an existing live Stripe
PaymentIntent instead of creating a second one if called again before
the first is confirmed. `payments.stripe_payment_intent_id` and
`payments.paypal_order_id` both carry a partial unique index (`WHERE
... IS NOT NULL`) as a database-level backstop against ever
double-recording the same provider payment, independent of whether the
application-level lock was taken.

## Schema

```
invoices
  id                  uuid pk
  customer_id         uuid fk -> users.id, on delete restrict
  status              text check (status in
                       ('draft','sent','paid','overdue','void'))
  amount_total         numeric(12,2) not null   -- denormalized sum of line items, recomputed on write
  currency             text not null default 'usd'
  memo                 text
  is_recurring          boolean not null default false
  recurrence_interval   text check (recurrence_interval in
                        ('weekly','monthly','quarterly','yearly') or null)
  due_date              date
  stripe_payment_intent_id  text unique          -- null until a payment attempt starts
  deleted_at            timestamptz null          -- soft delete, see 03
  created_at / updated_at

invoice_line_items
  id            uuid pk
  invoice_id    uuid fk -> invoices.id, on delete cascade
  description   text not null
  quantity      numeric(10,2) not null default 1
  unit_price    numeric(12,2) not null
  created_at

payments
  id                       uuid pk
  invoice_id               uuid fk -> invoices.id, on delete restrict
  method                   text not null default 'stripe', check (method in
                           ('stripe','paypal','zelle','in_person','other'))
  stripe_payment_intent_id text null, partial unique where not null
                           -- only set for method='stripe' rows
  paypal_order_id          text null, partial unique where not null
                           -- only set for a REAL PayPal API capture;
                           -- null for a manually-recorded PayPal payment
  recorded_by              uuid fk -> users.id, on delete set null, null
                           -- which admin recorded a manual payment
  note                     text null   -- free-form admin reference (Zelle
                           -- confirmation #, etc.), manual payments only
  amount                   numeric(12,2) not null
  status                   text check (status in
                            ('pending','succeeded','failed','refunded'))
  transaction_id            text   -- Stripe charge ID, for reconciliation
  created_at
```

`invoices.amount_total` is denormalized for query speed but must be
recomputed from `invoice_line_items` on every write inside the same
transaction, never trusted from client input -- a customer-controlled
invoice total is an obvious tamper vector.

## Endpoints

### Admin (`api/invoices.py`, `require_admin`)

- `POST /api/admin/invoices` -- create (draft), with line items
- `PATCH /api/admin/invoices/{id}` -- edit while draft; editing a `sent`
  invoice is restricted to memo/due_date (line items are frozen once
  sent, to keep what the customer was shown stable)
- `POST /api/admin/invoices/{id}/send` -- draft -> sent, triggers
  notification (email, out of scope for v1 -- stub the call site)
- `POST /api/admin/invoices/{id}/void` -- sent/overdue -> void
- `GET /api/admin/invoices` -- list/filter (status, customer, date range)
- `GET /api/admin/invoices/{id}` -- full detail including payments
- `GET /api/admin/invoices/{id}/pdf` -- professional PDF (any status,
  including draft -- see the PDF section below)
- `POST /api/admin/invoices/{id}/payments/manual` -- record a payment
  that happened outside the system (Zelle, in person, PayPal sent
  directly); body `{method, amount, note?}`. Marks the invoice `paid`
  once recorded payments cover `amount_total`; a partial payment stays
  recorded but leaves the invoice payable for the remainder.

### Customer (`api/invoices_public.py`, `require_customer`)

- `GET /api/invoices` -- list only `WHERE customer_id = session.user_id`
- `GET /api/invoices/{id}` -- 404 (not 403 -- don't leak existence) if
  not owned by the session's customer
- `POST /api/invoices/{id}/pay` -- creates a Stripe PaymentIntent,
  returns `client_secret` for Stripe.js to complete on the frontend.
  Rate-limited per [02-auth-and-security.md](02-auth-and-security.md)
  (20/min). Idempotent: if a still-live PaymentIntent already exists
  for this invoice, its `client_secret` is reused instead of creating a
  second one.
- `GET /api/invoices/payment-methods` -- `{stripe: true, paypal: bool}`,
  reflecting whether PayPal is actually configured right now.
- `POST /api/invoices/{id}/pay/paypal` -- creates a real PayPal order,
  returns `{order_id, approval_url}`; `503` if PayPal isn't configured.
- `POST /api/invoices/{id}/pay/paypal/capture` -- captures a PayPal
  order after the customer approves it on PayPal's site (PayPal
  redirects back with `?token=<order_id>`), records the payment, marks
  the invoice paid once covered.
- `GET /api/invoices/{id}/pdf` -- the same professional PDF as the
  admin route, ownership-checked.

### Webhooks (`api/webhooks.py`, no session auth -- Stripe signature only)

- `POST /api/webhooks/stripe` -- verifies `Stripe-Signature` header
  against `STRIPE_WEBHOOK_SECRET`, handles
  `payment_intent.succeeded`/`.payment_failed`, updates `payments` and
  `invoices.status` idempotently (keyed on `stripe_payment_intent_id` --
  webhook delivery is at-least-once, handlers must be safe to replay).

## PDF generation

Invoices render to a real, professional, printable PDF via LaTeX, not
a screenshot-style HTML-to-PDF conversion or the site's own visual
style -- an invoice is a financial/legal document meant to be printed
and archived, not site branding. See `domain/invoices/pdf/`:

- `logandinvoice.cls` -- a custom LaTeX document class (letterhead,
  itemized table, hyperlinked "Pay online" line that still shows the
  literal URL when printed).
- `invoice.tex.jinja` -- a Jinja2 template (custom `\VAR{}`/`\BLOCK{}`
  delimiters so it doesn't collide with LaTeX's own `{`/`}`/`%`).
- `renderer.py` -- assembles + **LaTeX-escapes** every field that isn't
  literal source this module wrote itself (memos, line-item
  descriptions, customer email) through one chokepoint
  (`build_invoice_pdf_data`) before it ever reaches the template, then
  shells out to `latexmk` to compile it.

Requires a real LaTeX toolchain at runtime (`latexmk` +
`texlive-latex-recommended`/`texlive-latex-extra`/
`texlive-fonts-recommended`) -- already installed in `backend/Dockerfile`
(a real, ~1GB image layer, an accepted tradeoff for PDF quality). Not
installed on every machine that runs the plain unit/integration test
suite; the tests that actually compile a PDF skip cleanly
(`shutil.which("latexmk") is None`) where it's missing, same
convention as the Postgres-testcontainers skip.

## Recurring invoices

A scheduled job (see [11-deployment.md](11-deployment.md) for the cron
mechanism) walks `invoices WHERE is_recurring AND status = 'sent'` past
their `recurrence_interval` and creates the next draft automatically.
This is a backend domain function (`domain/invoices/recurrence.py`),
not logic embedded in the cron entrypoint, so it's unit-testable without
a scheduler.

## Testing

Ownership isolation (`GET /api/invoices/{id}` cross-customer), webhook
idempotency, and amount-tampering rejection are the highest-value test
cases for this feature -- see
[12-testing-strategy.md](12-testing-strategy.md) for where each lives.
