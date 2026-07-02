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

## Go-live checklist -- gather these, in this order

Everything a first deploy needs, in the order you'd actually go get it.
Each line links to its own section below for the *how*; this is the
*what, and in what order* -- the single central place to work through
before running through [deployment.md](deployment.md) step by step.
Items marked **optional** can be skipped entirely for a first deploy
(the site works completely without them) and turned on later with zero
code changes, just an env var + restart. Once you've filled in
`backend/.env`, run [deployment.md](deployment.md)'s health check
(`make healthcheck`, or `docker compose exec backend python -m
logand_backend.scripts.health_check`) to verify every value actually
works (a real Postgres connection, a real Stripe API call, etc.), not
just that something is set.

**Required (the site does not run correctly without these):**

- [ ] A domain, with DNS A/AAAA records already pointing at the VPS's
      IP -- see [deployment.md](deployment.md)'s Prerequisites (Caddy's
      automatic HTTPS needs this live before it can get a certificate).
- [ ] `SESSION_SECRET` -- generate locally, see [its section](#session_secret) below.
- [ ] `POSTGRES_PASSWORD` / `DATABASE_URL` -- pick a real password, see [DATABASE_URL](#database_url).
- [ ] A Stripe account (test mode is fine to start) -- `PAYMENT_PROCESSOR_SECRET`,
      `STRIPE_WEBHOOK_SECRET`. See [PAYMENT_PROCESSOR_SECRET](#payment_processor_secret-stripe-secret-key).
- [ ] `PUBLIC_BASE_URL` -- your real domain, `https://...`.
- [ ] `INVOICE_BUSINESS_NAME` / `INVOICE_BUSINESS_DETAILS` / `INVOICE_CONTACT_EMAIL` --
      real business info for the invoice PDF letterhead.
- [ ] `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` -- to bootstrap the one
      admin account, then removed again. See [that section](#seed_admin_email--seed_admin_password).

**Strongly recommended before going live for real (not hard blockers, but you'll want them):**

- [ ] `BACKUP_R2_BUCKET` / `BACKUP_R2_ENDPOINT_URL` / `BACKUP_R2_ACCESS_KEY_ID` /
      `BACKUP_R2_SECRET_ACCESS_KEY` -- without these, nightly backups
      stage locally only and are lost along with everything else if the
      VPS itself is lost. See [that section](#backup_r2_bucket--backup_r2_endpoint_url--backup_r2_access_key_id--backup_r2_secret_access_key).
- [ ] GitHub Actions repo secrets (same values as `backend/.env`, plus
      `VPS_SSH_KEY`) -- needed for `deploy.yml` to work at all. See
      [GitHub Actions secrets specifically](#github-actions-secrets-specifically).

**Optional (skip for launch day, add later anytime):**

- [ ] `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` -- see [deployment.md](deployment.md)'s
      "Turning on PayPal later" section. Falls back to Zelle/in-person/manual recording without it.
- [ ] `SMTP_HOST` and friends, `MAILING_ADDRESS` -- invoice-sent/payment-received
      email notifications. See [that section](#smtp_host--smtp_port--smtp_username--smtp_password--smtp_use_tls--smtp_from_address).
      Silent no-op without it -- nothing else depends on email being deliverable.
- [ ] `STORAGE_BACKEND=r2` + `R2_*` -- switch file storage from the VPS's
      own disk to Cloudflare R2 once volume justifies it. See
      [design/13-storage-abstraction.md](design/13-storage-abstraction.md)
      for the local-vs-R2-vs-NAS tradeoffs, and [that section](#storage_backend--storage_local_dir--r2_)
      below for the swap itself -- it's a config change, not a migration,
      for any FILES uploaded after the switch (existing local files need
      an explicit one-time copy if you want them to also exist in R2, see that section).

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

### `STORAGE_BACKEND` / `STORAGE_LOCAL_DIR` / `R2_*`

Not secret except for `R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` -- see
[design/13-storage-abstraction.md](design/13-storage-abstraction.md) for
the full local-vs-R2-vs-NAS reasoning.

`STORAGE_BACKEND` is `local` (default) or `r2`. `local` needs nothing
else set (`STORAGE_LOCAL_DIR` defaults to `./data/storage`, gitignored).

To turn on R2: create an R2 bucket in the Cloudflare dashboard, create an
API token scoped to that bucket (**R2 > Manage API Tokens**), then set:

```
STORAGE_BACKEND=r2
R2_BUCKET=your-bucket-name
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<from the API token>
R2_SECRET_ACCESS_KEY=<from the API token>
```

`R2_PUBLIC_BASE_URL` is optional -- only set it if you've opted the
bucket into public read access via a custom domain (**R2 > bucket >
Settings > Public access**); leaving it unset means every file download
proxies through this backend's own authenticated API routes instead,
which is the safer default.

Rotating: revoke and recreate the API token in the Cloudflare dashboard,
update `backend/.env`/GitHub Actions, restart `backend`. Rotating does
NOT invalidate already-stored files -- only the credentials used to
access them.

### `BACKUP_R2_BUCKET` / `BACKUP_R2_ENDPOINT_URL` / `BACKUP_R2_ACCESS_KEY_ID` / `BACKUP_R2_SECRET_ACCESS_KEY`

Deliberately separate from the `R2_*` set above, even though they're
both R2 credentials -- these are `ops/backup.sh`'s off-box push
destination (nightly `pg_dump` + storage tarball), used regardless of
whether `STORAGE_BACKEND` is `local` or `r2`. Keeping them as separate
credentials/bucket means a bug or compromise in one can't touch the
other (the app can't accidentally overwrite backups, a backup-script
bug can't corrupt live application files).

**Set these before you consider the deployment's backups real** -- see
[deployment.md](deployment.md)'s Backups section. Without them,
`ops/backup.sh` still runs nightly and stages a local copy (logged as a
loud warning every run, visible in `docker compose logs backup`), but a
VPS-level failure takes that local copy down with everything else.

Setup: create a **second** R2 bucket (separate from any
`STORAGE_BACKEND=r2` bucket) in the Cloudflare dashboard specifically
for backups, create an API token scoped to only that bucket, then set:

```
BACKUP_R2_BUCKET=your-backup-bucket-name
BACKUP_R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
BACKUP_R2_ACCESS_KEY_ID=<from the API token>
BACKUP_R2_SECRET_ACCESS_KEY=<from the API token>
```

Verify it's actually working after setup:
`docker compose logs backup` after the next nightly run (03:00) should
show `backup pushed to r2://...`, not the "not fully configured"
warning. To test immediately rather than waiting:
`docker compose exec backup /usr/local/bin/backup.sh`.

Rotating: revoke and recreate the API token in the Cloudflare
dashboard, update `backend/.env`, restart the `backup` service
(`docker compose up -d backup`). Rotating does NOT invalidate
already-pushed backups.

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
