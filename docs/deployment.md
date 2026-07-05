# Deployment -- from a bare VPS to a running site

Audience: whoever is standing this up for the first time, or
redeploying after a long gap. See [design/11-deployment.md](design/11-deployment.md)
for the architectural *why*; this doc is the literal step-by-step.
See [secrets.md](secrets.md) for how to generate every value below --
**start with that doc's "Go-live checklist" section** if this is a
first deploy, then come back here for the actual commands.

## Prerequisites

- A VPS (2 vCPU / 4GB RAM minimum -- see
  [design/11-deployment.md](design/11-deployment.md)'s sizing note),
  Ubuntu or Debian, ports 80/443/22 reachable.
  Docker + Docker Compose + Node (for the one-time manual frontend
  build) + git + a firewall aren't installed yet on a bare VPS -- run
  `ops/setup-vps.sh` to install all of them in one idempotent pass
  (safe to re-run): `curl -fsSL <raw-url-to-this-repo>/ops/setup-vps.sh | sh`,
  or `sh ops/setup-vps.sh` once you've already cloned the repo some
  other way. It does NOT clone the repo, write secrets, touch DNS, or
  start the stack -- those stay explicit, separate steps below.
- A domain (or two -- the `Caddyfile` already handles `logand.app` and
  `logandapp.com` as aliases) with DNS **A/AAAA records pointing at the
  VPS's IP** before you start Caddy -- Caddy's automatic HTTPS
  (Let's Encrypt) fails its ACME challenge if DNS isn't live yet.
- A Stripe account (test mode is fine to start). PayPal is optional --
  skip it entirely for now if you don't have a PayPal developer account
  yet; nothing else in the deploy depends on it.

## 1. Clone and configure

```bash
git clone <this-repo-url> logand.app
cd logand.app
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in real values -- see [secrets.md](secrets.md)
for what each one is and how to generate it. At minimum for a first
deploy you need: `DATABASE_URL` (a real password, not `changeme`),
`SESSION_SECRET`, `PAYMENT_PROCESSOR_SECRET`, `STRIPE_PUBLISHABLE_KEY`
(the pk_ key from the same Stripe account+mode -- without it the
customer pay page hides the "Pay with card" option entirely),
`STRIPE_WEBHOOK_SECRET`, `PUBLIC_BASE_URL` (your real domain). Leave
`PAYPAL_*` unset for now -- see "Turning on PayPal later" below.

## 2. Build the frontend

The frontend is a static build Caddy serves directly (no frontend
container) -- see [design/10-seo-and-agent-accessibility.md](design/10-seo-and-agent-accessibility.md)
for why it's prerendered rather than a plain client-side SPA shell.

```bash
cd frontend
npm ci
npm run build   # outputs frontend/dist, which docker-compose.yml mounts into caddy
cd ..
```

Public project-showcase media (photos/videos/PDFs) is uploaded
separately, straight to R2, via
`backend/src/logand_backend/scripts/upload_public_asset.py` -- see
[design/13-storage-abstraction.md](design/13-storage-abstraction.md#public-assets-and-caching)
for the caching convention (long-lived immutable Cache-Control, new
key per replacement, never overwrite).

## 3. Bring up the stack

```bash
docker compose up -d postgres redis
docker compose --profile migrate run --rm migrate   # creates the schema fresh
docker compose up -d backend caddy backup
```

Confirm the backend is actually healthy before moving on:

```bash
curl -s https://yourdomain/api/me   # expect a 401 (not connection-refused/502) -- that's correct, means the backend answered
```

If Caddy can't get a certificate yet (DNS not propagated), it'll retry
automatically -- check `docker compose logs caddy` if `https://` isn't
answering after a few minutes.

## 4. Create the first admin account

There is no signup path to admin -- self-registration always creates a
customer account, by design (see [design/02-auth-and-security.md](design/02-auth-and-security.md)).
The one-time bootstrap:

```bash
# In backend/.env, temporarily add:
SEED_ADMIN_EMAIL=you@example.com
SEED_ADMIN_PASSWORD=a-real-password-you-will-change-immediately-after

docker compose up -d backend   # restart to pick up the new env vars
```

Log in at `https://yourdomain/login` with those credentials, confirm
you land on an admin-visible page (the nav shows "invoicing", not "my
invoices"). Then:

```bash
# Remove SEED_ADMIN_EMAIL/SEED_ADMIN_PASSWORD from backend/.env again
docker compose up -d backend   # restart once more
```

See [secrets.md](secrets.md)'s entry on this variable pair for why it
shouldn't stay set indefinitely.

## 5. Wire up Stripe webhooks

In the [Stripe dashboard](https://dashboard.stripe.com/webhooks), add
an endpoint: `https://yourdomain/api/webhooks/stripe`, subscribed to
`payment_intent.succeeded` and `payment_intent.payment_failed`. Copy
its signing secret into `backend/.env`'s `STRIPE_WEBHOOK_SECRET`,
restart `backend`.

Test it: create an invoice as admin, send it, pay it as the customer
with a [Stripe test card](https://docs.stripe.com/testing) (`4242 4242
4242 4242`, any future expiry/CVC), confirm the invoice flips to `paid`.

## 6. Turning on PayPal later (optional, anytime)

Nothing above depends on this -- the site works completely without it,
falling back to "pay via Zelle/PayPal-direct/in person, contact us."
When you're ready:

1. Create a REST API app in the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/applications).
2. Add its **Sandbox** Client ID/Secret to `backend/.env`
   (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_MODE=sandbox`),
   restart `backend`.
3. Test a full sandbox payment end to end (PayPal's sandbox gives you
   fake buyer accounts to pay with) before touching live credentials.
4. Once confirmed, swap in the app's **Live** credentials and
   `PAYPAL_MODE=live`, restart again.

## 7. CI/CD going forward

Once the above works, everyday deploys are just `git push` to `main`:
`.github/workflows/ci.yml` runs the full test pyramid, and
`.github/workflows/deploy.yml` builds images, ships them, and restarts
the backend over SSH after CI passes. Add the same secrets from step 1
to the repo's **Settings > Secrets and variables > Actions** so
`deploy.yml` can build with them (see [secrets.md](secrets.md)'s
GitHub Actions section) -- this is a one-time setup, not a
per-deploy step.

## Backups

`ops/backup.sh` runs nightly (see the `backup` service in
`docker-compose.yml`): `pg_dump` + a tarball of the storage volume,
staged locally, then pushed off-box to R2 via `rclone` -- see
[secrets.md](secrets.md)'s `BACKUP_R2_*` section for the credentials
this needs. **Set `BACKUP_R2_*` before you consider backups real** --
without it, the script still stages a local copy (logged loudly as a
warning every run) but a VPS-level failure takes that local copy down
with everything else, same as no backup at all. Retention: the 30 most
recent backups are kept in R2, older ones pruned automatically; local
staging only ever keeps the most recent 3 runs (it's a short buffer for
"the push itself broke," not the real retention store).

See [runbooks/restore.md](runbooks/restore.md) for the restore
procedure.

## Health check -- verify everything is actually wired up correctly

`backend/src/logand_backend/scripts/health_check.py` checks every real
subsystem/dependency against whatever `backend/.env` currently points
at -- not just "is a value set," but real, live checks: a real
`SELECT 1` against Postgres, a real Redis `PING`, a real Stripe API
call with your actual key, a real PayPal OAuth token fetch, a real
write/read/delete round trip against whichever storage backend is
configured (`local` or `r2`), and (unless `--skip-http`) a real HTTP
request to your own `PUBLIC_BASE_URL`.

Run it after any first deploy or config change:

```bash
docker compose exec backend python -m logand_backend.scripts.health_check
# or locally against backend/.env directly, before DNS/deploy is live:
cd backend && make healthcheck
```

Output is one line per check, colored and grouped by section:

- `[  OK]` -- verified working.
- `[WARN]` -- a graceful, expected fallback is active (PayPal/SMTP not
  configured, no off-box backup destination set, `latexmk` missing
  locally) -- not broken, just not fully set up yet. Review these, but
  they don't block anything.
- `[FAIL]` -- something is actually broken (can't reach Postgres, a
  real API key was rejected, still running the dev-only default
  `SESSION_SECRET`/`PAYMENT_PROCESSOR_SECRET`/`STRIPE_WEBHOOK_SECRET`).
  Exits non-zero if any check fails -- safe to wire into a post-deploy
  CI/CD step or a monitoring cron if you want an automated page on
  regression.

A clean first-deploy run should show zero `FAIL`s and only the `WARN`s
you're deliberately deferring (PayPal, SMTP, off-box backups are all
fine to defer -- see [secrets.md](secrets.md)'s Go-live checklist for
what's actually required vs. optional).

## Testing against the real production site

`scripts/prodtest/` is a separate, black-box test harness that exercises
the real running production site over real HTTPS (plus SSH to the VPS
for a couple of out-of-band checks) -- distinct from `backend/tests/`
and `frontend/tests/`, which run against disposable test instances. It
guarantees zero artifacts left behind (every mutation it makes is
reverted, verified, and its own cleanup mechanism has unit test coverage
in CI) and is never run automatically -- see
[scripts/prodtest/README.md](../scripts/prodtest/README.md) for how to
run it and why it's deliberately excluded from every CI workflow.

## Redeploying / restarting after config changes

Most `backend/.env` changes just need `docker compose up -d backend`
(recreates that one container with the new env). Frontend changes need
`npm run build` re-run and `docker compose restart caddy` (or just
`up -d caddy` again) to pick up the new `frontend/dist`. Database
migrations: `docker compose --profile migrate run --rm migrate` (safe
to run anytime, `alembic upgrade head` no-ops if already current).
