# 04 -- Invoices

Audience: anyone building invoice endpoints (admin or customer-facing)
or the payment integration. Read [00-overview.md](00-overview.md),
[02-auth-and-security.md](02-auth-and-security.md), and the `users`/
`sessions` tables in [03-database.md](03-database.md) first.

## Decision: payment processor is Stripe

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
  stripe_payment_intent_id text not null
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

### Customer (`api/invoices_public.py`, `require_customer`)

- `GET /api/invoices` -- list only `WHERE customer_id = session.user_id`
- `GET /api/invoices/{id}` -- 404 (not 403 -- don't leak existence) if
  not owned by the session's customer
- `POST /api/invoices/{id}/pay` -- creates a Stripe PaymentIntent,
  returns `client_secret` for Stripe.js to complete on the frontend.
  Rate-limited per [02-auth-and-security.md](02-auth-and-security.md)
  (20/min).

### Webhooks (`api/webhooks.py`, no session auth -- Stripe signature only)

- `POST /api/webhooks/stripe` -- verifies `Stripe-Signature` header
  against `STRIPE_WEBHOOK_SECRET`, handles
  `payment_intent.succeeded`/`.payment_failed`, updates `payments` and
  `invoices.status` idempotently (keyed on `stripe_payment_intent_id` --
  webhook delivery is at-least-once, handlers must be safe to replay).

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
