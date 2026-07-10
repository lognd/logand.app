# 16 -- Contact users, email verification, and invoice claiming

Status: implemented (2026-07-09).

## Problem

Two asks, one schema:

1. Invoice someone who has no account, addressed only by their email. If they
   later create an account with that email, their invoice history is already
   there.
2. Do it without handing an attacker somebody else's billing history.

Today `domain/auth/service.py::register` is open self-registration with **no
proof of email ownership**. `invoices.customer_id` is a `NOT NULL` FK to
`users.id`, and `users.password_hash` is `NOT NULL`.

Naively relaxing (1) -- attach invoices to whoever signs up with a matching
email -- turns unverified self-registration into account takeover of billing
data: register `victim@example.com`, receive their invoices, amounts, memos,
PDFs, and pay links. So (2) is a hard prerequisite for (1), not a nicety.

## Shape of the fix

Keep `invoices.customer_id NOT NULL -> users.id`. Do **not** add a nullable
`customer_email` to `invoices`; that would fork every join, every stats query,
and every PDF/notification path into "user or email" branches. Instead widen
what a `users` row is allowed to mean.

A `users` row now occupies one of three states:

| State | `password_hash` | `email_verified_at` | Can log in | Sees invoices |
|---|---|---|---|---|
| contact | `NULL` | `NULL` | no | no |
| unverified | set | `NULL` | no | no |
| active | set | set | yes | yes |

- **contact** -- created by an admin invoicing an email that has no user.
  It is addressable (invoices FK to it, mail goes to it) but it is not an
  account: nothing can authenticate as it.
- **unverified** -- someone claimed the address via `register` but has not
  proven they control the inbox.
- **active** -- inbox control proven.

"Attaching invoices at signup" therefore does not exist as an operation. The
invoice is *already* on the row from the moment the admin created it. Signup
does not move data; it upgrades the row's state. This is the whole trick, and
it is why there is no merge/backfill step to get wrong.

### The load-bearing invariant

> Invoice visibility is gated on `email_verified_at IS NOT NULL`, never on
> mere linkage.

Linkage is established by an admin who typed an email address. Only clicking a
link in that inbox establishes ownership. Every customer-facing invoice read
path (`api/invoices.py` list/detail, `api/invoices_public.py` pay routes,
PDF export) enforces the verified check. Getting this wrong reintroduces the
takeover, so it is asserted directly in `tests/system/test_invoice_claiming.py`.

### Squatting

An attacker registering `victim@example.com` before the victim leaves the row
in **unverified**. Registration against an *unverified* row is allowed and
simply overwrites `password_hash` and re-sends verification -- an unverified
row is not "owned" by anyone, so this is not a takeover, and it is what stops
the attacker from denial-of-servicing the real owner out of their own address.
Registration against an **active** row is refused (email already in use).

Whoever controls the inbox wins. That is the only correct tiebreak.

## Schema (migration `0028_contact_users_verification`)

(Renumbered from 0022 on merge: the tax subsystem had already taken 0022-0027,
and two migrations sharing a `down_revision` fork the Alembic graph into two
heads, which makes `alembic upgrade head` fail on deploy. The revision id is
also capped at 32 chars by `alembic_version.version_num`.)

```
users.password_hash      TEXT  NOT NULL -> NULL      (NULL = contact, no account)
users.email_verified_at  TIMESTAMPTZ NULL           (new)

email_verification_tokens              (new; mirrors password_reset_tokens)
  id            uuid pk
  user_id       uuid fk -> users.id ON DELETE CASCADE
  token_hash    text unique not null   -- sha256(raw), never the raw token
  purpose       text not null          -- 'verify' | 'claim'
  expires_at    timestamptz not null
  used_at       timestamptz null       -- single-use, like password reset
  created_at    timestamptz not null
```

**The migration MUST backfill `email_verified_at = now()` for every existing
row.** Every current user has a password and predates this feature; leaving
them `NULL` locks the entire existing customer base and the seeded admin out
of login on deploy. This is the single most dangerous line in the change.

`ck_users_contact_or_active`: a row with `email_verified_at IS NOT NULL` must
have `password_hash IS NOT NULL`. (A verified row with no password is
meaningless and would be a login-bypass shaped hole.)

## Token flows

One table, one code path, two `purpose` values -- not two parallel token
systems. Reuse `auth/tokens.py::hash_token` and the
`domain/auth/password_reset.py` structure verbatim; do not reimplement
hashing, expiry, or single-use checks.

Both purposes are the SAME operation, `_redeem_and_activate`, differing only
in `purpose`. Redeeming a token takes a password and sets `password_hash`
**and** `email_verified_at` in one transaction. Clicking the emailed link
*is* the proof of inbox control, so the party that proves inbox control is
also the party that chooses the credential. Redemption is refused against an
already-active row: an active row's password is owned, and a stale token of
either purpose must never rewrite it.

**verify** -- minted by `register`. Emailed as
`{public_base_url}/verify-email?token=...`.

**claim** -- minted by `notify_invoice_sent` when the recipient is a *contact*
row. Emailed as `{public_base_url}/claim?token=...` alongside the invoice.

Both are single-use and expire (`claim` gets a long TTL -- an invoice email
may sit unread for weeks; `verify` gets 24h).

### Why `register` stores no password (FINDINGS-auth-2026-07-10 H1)

`register` originally wrote `password_hash` onto the row and `verify` merely
flipped `email_verified_at`. That binds the token to the ROW, not to the
credential live when it was minted -- and an unverified row's password is
deliberately overwritable (that is what prevents squatting). So an attacker
could re-register a victim's pending address, replacing the password, and the
victim's own click would then activate the account **with the attacker's
password**. Deterministic takeover of billing data.

Hence: **`register` writes no credential on any branch.** A registered row
stays a contact (`password_hash IS NULL`) until somebody redeems a token.
There is no planted credential for a victim's click to turn on. Registration
therefore takes an email only; the password is chosen at redemption.

Residual, accepted: re-registering invalidates the prior pending token, so an
attacker can nuisance-invalidate a victim's unclicked link. Every replacement
still goes to the victim's inbox, and `resend-verification` recovers. That is
an annoyance, not a takeover.

## API

```
POST /api/auth/register            {email}           -> 202, mints verify token,
                                   mails it. NO password field: see H1 above.
POST /api/auth/verify-email        {token, password}  -> 204, row becomes active
POST /api/auth/resend-verification {email}            -> 202 (always, no oracle)
GET  /api/auth/claim               ?token=            -> invoice preview (no auth)
POST /api/auth/claim               {token, password}  -> 204, row becomes active
POST /api/invoices                 now accepts customer_email as an alternative
                                   to customer_id; get-or-creates a contact row
```

`login` rejects `password_hash IS NULL` with the same generic invalid-credentials
error as a bad password (no account-existence oracle), and still runs
`verify_password` against `DUMMY_PASSWORD_HASH` so the timing does not fork.
It rejects `email_verified_at IS NULL` with a distinct, non-generic
"verify your email" error -- that one is safe to disclose, because reaching it
requires already knowing the correct password.

`resend-verification` always returns 202 regardless of whether the address
exists, matching `request_password_reset`'s existing no-oracle behavior.

## Consequences

- `ensure_admin_seeded` must set `email_verified_at`, or the deploy's own admin
  cannot log in.
- Anywhere that reads `user.password_hash` must tolerate `None`.
- Deleting a contact row is still blocked by `ondelete="RESTRICT"` on
  `invoices.customer_id`, which is correct: you cannot delete someone you have
  billed.
