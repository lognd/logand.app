# Secrets -- what exists, where it lives, how to rotate it

Audience: whoever is deploying or operating this site. Read
[deployment.md](deployment.md) first if you're setting things up for
the first time; this doc is specifically about the secret *values*
themselves, not the deploy mechanics around them.

**Hard rule, repeated from [design/00-overview.md](design/00-overview.md):
nobody (human or AI agent) should ever `cat`, print, log, or echo the
real contents of `backend/.env` or any GitHub Actions secret.** Generate
new values, write them into the right place, and move on -- don't read
existing ones back out to "confirm" them.

## Where secrets live

| Secret | Lives in | Never lives in |
|---|---|---|
| Everything below | `backend/.env` (gitignored, VPS-local) | git, logs, chat, this repo |
| `VPS_SSH_KEY`, and copies of everything below | GitHub Actions repo secrets (`Settings > Secrets and variables > Actions`) | anywhere in workflow YAML as a literal value |

`backend/.env.example` documents every variable's *name* and a fake
placeholder value -- copy it to `backend/.env` and fill in real values,
never the other way around.

## Full list, and how to generate/rotate each one

### `DATABASE_URL`

Postgres connection string, `postgresql+asyncpg://user:password@host:5432/db`.
Rotating the password: change it in Postgres itself
(`ALTER USER logand WITH PASSWORD '...'`), update `backend/.env` and the
GitHub Actions secret to match, then restart the `backend` container
(`docker compose up -d backend`). Rotate immediately if it's ever been
exposed (a screenshot, a support ticket, anywhere outside `.env`/GitHub
secrets).

### `REDIS_URL`

Only meaningful if Redis is actually reachable at that address --
`domain`/`auth/rate_limit.py`'s `RateLimiter` falls back to an
in-process limiter if this is unset or unreachable, so an app instance
never hard-fails just because Redis is briefly down. No credential to
rotate unless you've put a password on Redis yourself (recommended for
anything beyond a single-VPS deployment where Redis isn't
network-exposed at all).

### `SESSION_SECRET`

HMAC key for signing **CSRF tokens** (session IDs themselves are random,
not signed -- see [design/02-auth-and-security.md](design/02-auth-and-security.md)).

Generate:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Rotating this invalidates every CSRF token currently held by an open
browser tab** -- users mid-session will see their next state-changing
request (login, pay, admin action) rejected with a 403 and need to
reload. Session cookies themselves are unaffected (they're validated
against the `sessions` table, not this key), so a reload/re-fetch of
CSRF token is all that's needed, not a re-login. Safe to rotate anytime;
plan for a brief "please refresh the page" blip for anyone actively
using the site at that moment.

### `PAYMENT_PROCESSOR_SECRET` (Stripe secret key)

From the [Stripe dashboard](https://dashboard.stripe.com/apikeys) --
`sk_test_...` for Stripe's test mode, `sk_live_...` for real charges.
**Never commit a real value** -- `backend/.env.example` only ever has
`sk_test_fake`, a value that isn't a real Stripe key at all.

Rotating: generate a new key in the Stripe dashboard (this
automatically revokes the old one after a grace period Stripe manages),
update `backend/.env` and GitHub Actions, restart `backend`. Do this
immediately if a key is ever exposed -- Stripe lets you roll keys
without any other config changes.

### `STRIPE_WEBHOOK_SECRET`

From the Stripe CLI (`stripe listen --print-secret`, for local dev) or
the Stripe dashboard's webhook endpoint configuration (for production,
once a real `https://yourdomain/api/webhooks/stripe` endpoint is
registered there). Rotating: create a new webhook endpoint (or roll the
signing secret on the existing one) in the Stripe dashboard, update
`backend/.env`/GitHub Actions, restart `backend`.

### `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`

Fully optional -- see [design/04-invoices.md](design/04-invoices.md)'s
"Decision: payment processor is Stripe (primary), with alternatives"
section for what happens when these are unset (nothing breaks; PayPal
just isn't offered as a checkout option, and the site quietly falls
back to "pay via Zelle/PayPal-direct/in-person, contact us").

To turn PayPal on: create a REST API app in the
[PayPal Developer Dashboard](https://developer.paypal.com/dashboard/applications),
copy its Client ID and Secret. Use the **Sandbox** app's credentials
first (`PAYPAL_MODE=sandbox`) to test the flow end to end without
moving real money; switch to a **Live** app's credentials and
`PAYPAL_MODE=live` only once you've verified a full sandbox payment
actually completes.

Rotating: regenerate the secret for the same app in the PayPal
dashboard, update `backend/.env`/GitHub Actions, restart `backend`.

### `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`

**Not a long-lived secret -- an opt-in bootstrap mechanism.** Setting
both creates (or resets the password of) an admin account with those
credentials on every app startup (see
`domain/auth/service.py::ensure_admin_seeded`). There is no other way
to create an admin account (self-registration always creates a
customer, by design).

Recommended usage:
1. Set both in `backend/.env`, deploy/restart once.
2. Log in as that admin through the real site, confirm it works.
3. **Remove both variables from `backend/.env` and restart again.** A
   production deployment shouldn't carry a well-known admin password in
   an env var indefinitely -- once the account exists, this mechanism's
   job is done.

If you ever need to reset the admin password later, temporarily set
both again (a new password this time), restart, confirm, remove again.

### `PUBLIC_BASE_URL`

Not really a secret, but gets it wrong and PayPal's redirect-back flow
and invoice-PDF "Pay online" links silently point at the wrong host.
Set to the real public URL the site is served at (e.g.
`https://logand.app`) -- never `localhost` in production.

### `INVOICE_BUSINESS_NAME` / `INVOICE_BUSINESS_DETAILS` / `INVOICE_CONTACT_EMAIL`

Not secret at all -- shown on every generated invoice PDF's letterhead.
Just real business information, no rotation concept applies.

### `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_USE_TLS` / `SMTP_FROM_ADDRESS`

Fully optional -- like PayPal above, unset means
`domain/notifications/mailer.py::is_configured` is False and every
notification (invoice sent, payment received) is a silent no-op.
Nothing in the invoice/payment flow depends on email actually being
deliverable.

To turn email on with **Google Workspace**: enable 2-Step Verification
on the sending account, generate an
[App Password](https://myaccount.google.com/apppasswords) (a regular
account password will not work with SMTP), then set:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=billing@yourdomain.com
SMTP_PASSWORD=<the 16-character app password>
SMTP_USE_TLS=true
SMTP_FROM_ADDRESS=billing@yourdomain.com
```

Any other SMTP provider (Postmark, SES, Fastmail, a self-hosted MTA,
etc.) works the same way -- just point `SMTP_HOST`/`SMTP_PORT` at it
and use its own credentials.

Rotating: regenerate the app password/API key at the provider, update
`backend/.env`/GitHub Actions, restart `backend`.

### `MAILING_ADDRESS`

Not secret, but legally required once email is turned on: CAN-SPAM
requires a valid physical postal address in every commercial email's
footer (`domain/notifications/mailer.py` puts this in the footer of
every notification it sends). Deliberately empty by default so a
placeholder-looking address never ships to production by accident --
set this to your real business mailing address before setting
`SMTP_HOST`.

### `SESSION_SECRET` also signs unsubscribe links

Worth calling out here since it's easy to miss: the one-click
unsubscribe token in every notification email's `List-Unsubscribe`
header (`domain/notifications/mailer.py::sign_unsubscribe_token`) is an
HMAC over `SESSION_SECRET`, the same secret documented above -- no
separate secret to manage. Rotating `SESSION_SECRET` invalidates every
unsubscribe link already sent (a real but minor tradeoff: anyone
rotating this secret should expect a few stale unsubscribe links to
require a fresh email before they work again).

## GitHub Actions secrets specifically

`.github/workflows/deploy.yml` reads `VPS_SSH_KEY` and copies of the
Stripe/session secrets above to build and ship the backend image and
restart it over SSH. Add/update these under the repo's
**Settings > Secrets and variables > Actions**. Never reference a
secret's value directly in workflow YAML output (no `echo
${{ secrets.X }}`) -- GitHub masks known secret values in logs, but
that masking is best-effort, not a substitute for just not printing
them.

## If a secret is ever actually exposed

1. Rotate it immediately using the steps above -- don't wait to
   investigate first, an exposed credential is exploitable the moment
   it's public regardless of how it got there.
2. If it was committed to git (even briefly, even in a since-reverted
   commit), treat the *value* as burned permanently -- rotating it is
   sufficient, you do not also need to rewrite git history to remove a
   value that's already been rotated (the old value is worthless once
   rotated; scrubbing history is about removing something still-valid,
   see the note in [00-overview.md](design/00-overview.md)).
3. Check the relevant provider's own access/audit logs (Stripe,
   PayPal, your VPS provider) for anything that happened using the
   exposed credential before you rotated it.
