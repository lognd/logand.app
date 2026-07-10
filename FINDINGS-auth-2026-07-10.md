# Auth / email-verification / invoice-claiming audit -- 2026-07-10

Scope: the `docs/design/17` feature (contact users, email verification, invoice
claiming). This code was excluded from the 2026-07-09 audit because it was being
written at the time, so this is its first review. Target invariant under attack:
"invoice visibility is gated on email_verified_at, never on mere linkage."

Result: **1 HIGH, 0 MEDIUM, 3 LOW.**

Production exposure at time of discovery: **none**. `SELECT` against prod showed
0 contact rows, 0 unverified rows, 2 active users. H1 requires a contact or
unverified row to exist; registering against an *active* row is refused. The
window would have opened the moment the first stranger was invoiced or the first
new user registered.

## HIGH

### H1 -- Account takeover: `verify_email` decoupled inbox-proof from password-setting [FIXED]

- **Where**: `domain/auth/service.py::register` (the overwrite-on-contact/unverified
  branch) together with `domain/auth/email_verification.py::verify_email`.
- **What was wrong**: `register()` on an existing contact/unverified row overwrote
  `password_hash` with the caller's password and minted a fresh `verify` token
  emailed to the row's address. `verify_email()` then set `email_verified_at` and
  nothing else -- it never rebound the password. The token was bound to the ROW,
  not to the credential that was current when it was minted. Since an unverified
  row's password is deliberately overwritable by anyone ("not owned by anyone",
  which is what stops squatting), the party who last set the password and the
  party who supplies the inbox proof need not be the same person.
- **Failure scenario (deterministic)**:
  1. Victim registers `victim@example.com` / `Vpass1234`. Row:
     `password_hash=hash(Vpass1234)`, `email_verified_at=NULL`. Token `TV` mailed
     to the victim.
  2. Before the victim clicks, the attacker POSTs
     `/api/auth/register {email: "victim@example.com", password: "Apass1234"}`.
     `register()` finds the unverified row and overwrites
     `password_hash=hash(Apass1234)`, minting token `TA` -- also mailed to the
     victim (the attacker never sees it, and does not need to).
  3. The victim clicks a verification link from their own inbox. It sets
     `email_verified_at`. The row is now ACTIVE with the ATTACKER's password.
  4. The attacker logs in with `Apass1234` and reads every invoice, amount, memo
     and PDF belonging to that address.
  Also reachable against a pure contact row: an admin invoices
  `victim@example.com`, the attacker registers that address, and the victim's
  inbox now holds both a claim link (safe -- `claim` sets the clicker's password)
  and a verify link (unsafe).
- **Fix applied**: `verify` and `claim` are now literally the same operation.
  `POST /api/auth/verify-email` takes `{token, password}` and installs that
  password while setting `email_verified_at`, in one transaction -- exactly what
  `claim` already did. `register` no longer writes `password_hash` at all; the
  row stays a contact (`password_hash IS NULL`) until somebody proves inbox
  control, and the password is chosen by whoever holds the token. An attacker can
  no longer choose a credential that a victim's click will activate.
  No schema change was required.

## LOW

### L1 -- `admin_reset_password` on a contact row leaves an unusable account [FIXED]

- **Where**: `domain/users/service.py::admin_reset_password`; `get_customer`
  admits any `role == "customer"` row, including a contact.
- **What was wrong**: Setting `password_hash` without `email_verified_at` moved a
  contact row to "unverified". `login()` then rejects with `EmailNotVerified` and
  no verify token is ever minted. The admin sees success and believes the customer
  can log in. They cannot. Not a security bypass (login stays gated), but a dead
  end the admin cannot diagnose.
- **Fix applied**: refuses a contact row with a distinct, actionable error rather
  than silently half-creating an account.

### L2 -- An invoice billed to an admin's own email is invisible in every portal [ACCEPTED, guarded]

- **Where**: `service.py::get_or_create_contact_user` returns any existing row
  unchanged; `api/invoices.py` attaches the invoice to it.
- **What's wrong**: `api/invoices_public.py` sits behind `require_customer`, which
  rejects `role == "admin"`, and `notify_invoice_sent` mints no claim token for a
  row that already has a password. An invoice FK'd to an admin row can never be
  opened or paid online. Data is stranded, never leaked.
- **Fix applied**: `create_invoice` now rejects a `customer_email` that resolves to
  a non-customer row, with a clear error, rather than stranding the invoice.

### L3 -- Verify/claim tokens ride in the URL, exposed via Referer until scrubbed [FIXED]

- **Where**: `api/auth.py` and `notify.py` build `?token=...` URLs;
  `VerifyEmail.tsx` / `Claim.tsx` scrub only after the first request settles, and
  `Claim.tsx` never scrubs on a failed preview.
- **What's wrong**: any cross-origin subresource loaded by those pages receives the
  live single-use token in the `Referer` header before the scrub, and could redeem
  it. Same class as the pre-existing password-reset link.
- **Fix applied**: both routes now emit `<meta name="referrer" content="no-referrer">`.

## Verified correct (do not re-audit)

- **Redemption atomicity / single use**: `_redeem_token` is one conditional
  `UPDATE ... WHERE used_at IS NULL AND expires_at > now() RETURNING user_id`. A
  concurrent double-redeem lets exactly one win; the loser gets `TokenInvalid`.
- **Expiry enforced on both purposes** (verify 24h, claim 30d), including in
  `get_claim_preview`.
- **No purpose confusion**: every lookup filters on `purpose`, so a `verify` token
  cannot be redeemed as a `claim` token or vice versa.
- **Raw tokens never stored, logged, or returned**: only `sha256(token)` is
  persisted (unique); logs carry `user_id` and `purpose` only.
- **`get_claim_preview` does not redeem** and discloses a strict subset of what the
  token already entitles the holder to.
- **No login oracle**: `verify_password(password, DUMMY_PASSWORD_HASH)` runs on both
  the no-such-user branch and the null-password branch, both returning
  `InvalidCredentials`. `EmailNotVerified` is only reachable after a correct
  password, so it discloses nothing to someone who does not already know it.
- **Session gate covers every customer read path**: `validate_session` rejects
  `email_verified_at IS NULL`; every `invoices_public.py` route is behind
  `require_customer`.
- **Squatting**: register-over-contact/unverified re-mints, so a real owner is never
  permanently locked out of their own address.
- **Migration 0028**: backfills before adding the check constraint; the downgrade
  gives contact rows a valid argon2 hash before re-imposing NOT NULL.
- **`ensure_admin_seeded`** sets `email_verified_at` on both branches.
