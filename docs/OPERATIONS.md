# Operations runbook

Audience: the owner (Logan, logan@logandapp.com), reading this either at
2am because something is broken, or six months from now having forgotten
everything. Every command below was verified against this repo -- if you
find one that stopped matching reality, fix the command, not this note.

This doc covers day-2 operations: deploying, migrations, email, Android
releases, invoicing without an account, payments, common failures, and a
pre-push checklist. For first-time VPS setup, see
[deployment.md](deployment.md). For secrets, see [secrets.md](secrets.md).
For disaster recovery, see [runbooks/restore.md](runbooks/restore.md).

## 1. Deploying

`.github/workflows/deploy.yml` triggers on every push to `main` (except
pushes that touch only `android/**`). It runs three jobs in sequence:

1. **`wait-for-ci`** -- polls `gh api repos/<repo>/commits/<sha>/check-runs`
   for the `backend`, `frontend`, `wasm-ascii`, and `system-tests` check
   runs on this exact commit, every 20s, up to 30 minutes. If any of them
   is not `success` once all are complete, it aborts with "CI did not pass
   cleanly for this SHA" and nothing downstream runs. `ci.yml` is a
   **separate** workflow that starts on the same push -- deploy.yml does
   not depend on it via `workflow_run`, it just polls for the same SHA's
   results.
2. **`build-and-push`** -- builds and pushes the backend image to
   `ghcr.io/lognd/logand.app/backend` (tagged `:latest` and `:<sha>`),
   builds the frontend (including a wasm-ascii rebuild step), uploads the
   static `frontend/dist` as an artifact.
3. **`deploy`** -- rsyncs `frontend/dist` to the VPS, then over SSH: `git
   fetch origin main && git reset --hard origin/main`, `docker compose pull
   backend scheduler`, `docker compose --profile migrate run --rm migrate`
   (alembic upgrade head -- see section 2), then `docker compose up -d
   backend caddy scheduler`.

So: pushing to `main` with red CI never deploys. Pushing to `main` with
green CI deploys automatically -- there is no manual "click to deploy"
step.

### Watching a deploy

```bash
gh run list --workflow=deploy.yml --limit 5
gh run watch <run-id>                     # live-follow the run in progress
gh run view <run-id> --log-failed         # only the failed step's log, if it failed
```

### Checking what's actually live

```bash
ssh hetzner 'cd /home/logand/logand.app && docker compose ps'
```

Containers are named with the `logandapp-` prefix (Docker Compose derives
the project name from the directory `logand.app`, stripping the dot), e.g.
`logandapp-backend-1`, `logandapp-scheduler-1`, `logandapp-postgres-1`,
`logandapp-redis-1`, `logandapp-caddy-1`, `logandapp-backup-1`.

To confirm the exact commit and dependency versions running right now,
hit the admin-only version endpoint (log in as admin first; it's gated by
`require_admin`):

```bash
curl -s https://logand.app/api/admin/version -H "Cookie: <your session cookie>" | jq .
```

`git_commit` comes from the `GIT_COMMIT` build-arg baked into the image at
build time (see `backend/Dockerfile` and `deploy.yml`'s `build-args:`) --
it reads "unknown" only when running outside a real built image (e.g.
local `uv run`).

### Tailing logs

```bash
ssh hetzner 'cd /home/logand/logand.app && docker compose logs -f backend'
ssh hetzner 'cd /home/logand/logand.app && docker compose logs -f scheduler'
ssh hetzner 'cd /home/logand/logand.app && docker compose logs --since 1h backend'
```

`backend` and `scheduler` share the `app_logs` volume (mounted at the
image's `LOG_DIR`, default `./logs`), so `/api/admin/logs` in the app
itself shows both processes' activity, not just the API server's.

## 2. Database migrations

Migrations live in
`backend/src/logand_backend/db/migrations/versions/` (currently
`0000_initial_schema.py` through `0028_contact_users_verification.py`).

### CRITICAL: the test suite does NOT prove a migration works

`backend/tests/conftest.py::db_engine` builds the schema with
`Base.metadata.create_all()` straight from the ORM models -- it never runs
Alembic. A green `uv run pytest` run tells you the ORM models and app code
are consistent with each other. It tells you **nothing** about whether
`alembic upgrade head` actually applies cleanly against a real Postgres,
whether a migration's `upgrade()`/`downgrade()` functions are even
syntactically correct, or whether a backfill step you wrote (e.g. "set
`email_verified_at = now()` for every existing row") actually runs. You
must test migrations by hand, separately, every time.

### Checking versions

Local/repo head:

```bash
cd backend && uv run alembic heads
```

Expect exactly **one** line, e.g. `0028_contact_users_verification (head)`.
Two lines means two migration branches were merged off the same parent
without one rebasing onto the other -- see "two heads" below.

Deployed revision (what's actually applied on prod):

```bash
ssh hetzner 'cd /home/logand/logand.app && docker compose exec postgres psql -U logand -d logand -c "select version_num from alembic_version;"'
```

`alembic_version.version_num` is `varchar(32)` -- this is why every
revision id in this repo is a short truncated slug (e.g.
`0020_password_reset_tok`, not the full descriptive name) rather than a
full migration filename stem. Don't "fix" a revision id to be more
readable without checking it still fits in 32 characters.

### Testing a migration by hand before you trust it

The backend already depends on `testcontainers[postgres]`
(`backend/pyproject.toml`) for exactly this. Spin up a throwaway Postgres
and run real Alembic against it:

```bash
cd backend
python3 - <<'EOF'
from testcontainers.postgres import PostgresContainer
import subprocess, os

with PostgresContainer("postgres:16-alpine") as pg:
    url = pg.get_connection_url().replace("psycopg2", "psycopg")
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], env=env, check=True)
    subprocess.run(["uv", "run", "alembic", "downgrade", "-1"], env=env, check=True)
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], env=env, check=True)
EOF
```

If your new migration has a data backfill (like 0028's
`email_verified_at = now()` backfill for existing rows), seed a row with
`INSERT` before running `upgrade head` and check the backfill actually
touched it -- an empty throwaway database will never exercise that path.

### Two heads (this has actually happened)

If two branches each add a migration with the same `down_revision` (both
pointing at the same parent revision), you get two heads:

```
$ uv run alembic heads
0027a_some_branch (head)
0027b_other_branch (head)
```

`alembic upgrade head` (what `docker compose --profile migrate run --rm
migrate` runs on every deploy) then either errors outright or picks a
non-deterministic one, and the deploy is broken. Fix: edit one of the two
new migrations' `down_revision` to point at the other one instead of
their shared parent, so they chain (`A -> B -> C`) instead of forking
(`A -> B`, `A -> C`). Always run `uv run alembic heads` before pushing to
main and confirm exactly one line comes back -- this is also in the
pre-push checklist below.

## 3. Email

Prod sends mail via **Gmail OAuth2 (domain-wide delegation)**, not SMTP:
`GMAIL_SERVICE_ACCOUNT_JSON` (the full service-account JSON key) +
`GMAIL_SENDER_EMAIL` (the mailbox it impersonates). Both must be set
together -- see `mailer.py::_gmail_oauth_configured`. `SMTP_HOST` is a
second, independent way to configure mail (used by `docker-compose.test.yml`'s
mailpit for system tests) but prod does not use it.

`mailer.py::is_configured` is `True` if EITHER SMTP or Gmail OAuth is
configured. Nothing in the invoice/payment flow depends on mail being
configured -- but registration does.

### What breaks if mail is broken

Registration (`POST /api/auth/register`) still returns 202 even if mail
fails to send -- the verification email is best-effort. A **new** user can
therefore register, never receive the verification link, and be
permanently stuck unable to log in (login requires `email_verified_at IS
NOT NULL` -- see section 5). **Existing, already-verified users are
completely unaffected** -- this only breaks new signups and the
claim-an-invoice flow for brand-new contacts.

### Checking mail config on prod without ever printing secrets

Never `cat` `backend/.env` on prod. Check only booleans, from inside the
running container:

```bash
ssh hetzner 'cd /home/logand/logand.app && docker compose exec backend python -c "
from logand_backend.app.config import AppConfig
from logand_backend.domain.notifications.mailer import is_configured, _gmail_oauth_configured
cfg = AppConfig.from_env()
print(\"mail configured:\", is_configured(cfg))
print(\"gmail oauth configured:\", _gmail_oauth_configured(cfg))
print(\"smtp configured:\", bool(cfg.smtp_host))
"'
```

### Resending a verification email

If a user reports "I registered but never got the email," don't dig
through logs first -- have them (or you, as admin) call:

```
POST /api/auth/resend-verification   {"email": "user@example.com"}
```

This always returns the same 202 body regardless of whether the email
exists, is already verified, or genuinely fails to send (see
`frontend/src/app/routes/public/VerifyEmail.tsx`'s own comment on this) --
that's deliberate, to avoid leaking which addresses have accounts. It is
rate-limited (see `api/auth.py`'s `resend_verification_route`). If the
user still doesn't get it after a resend, the problem is mail delivery
(check config above), not the app logic.

## 4. Android release keystore

Reference: `android/README.md` and `android/app/build.gradle.kts`.

### The four GitHub secrets

| Secret | Value |
|---|---|
| `LOGAND_KEYSTORE_B64` | `base64 -w0 logand-release.jks` of the whole keystore file |
| `LOGAND_KEYSTORE_PASSWORD` | the keystore password |
| `LOGAND_KEY_ALIAS` | the `-alias` used when generating the keystore (`logand` by convention) |
| `LOGAND_KEY_PASSWORD` | the key password |

If any of these is unset or blank, `app/build.gradle.kts`'s `release`
signing config **silently falls back to AGP's auto-generated debug
signing** -- the build still succeeds, the APK still installs standalone,
it just isn't signed with the real key. Verify what a release APK was
actually signed with:

```bash
apksigner verify --print-certs app-release.apk
```

Compare the certificate fingerprint against a known-good previous
release. If it matches AGP's well-known debug cert instead of your real
one, a secret is missing or empty in the repo's Actions settings.

### Cutting a release

1. In `android/app/build.gradle.kts`, bump **both**:
   ```kotlin
   versionCode = <previous + 1>   // must strictly increase
   versionName = "X.Y.Z"          // must actually change
   ```
2. Commit, push to `main`.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. `.github/workflows/release-android.yml` builds a release-signed APK
   and attaches it to a GitHub Release automatically.

**Both fields matter for different reasons:**
- `versionCode` must strictly increase or Android refuses the install
  outright ("An older version of this app can't be installed...").
- The in-app updater (`ui/update/UpdateViewModel.kt`) compares the latest
  release tag against `BuildConfig.VERSION_NAME` at runtime. If you bump
  `versionCode` but forget `versionName`, the app is installable but the
  updater sees the same `VERSION_NAME` forever and shows "update
  available" in a permanent loop that never resolves, because from its
  point of view the currently-installed version never matches what it
  thinks it already has.

### If the keystore is lost

There is no recovery. Every user who already installed a release build
signed with the lost key can **never install an update over that install
again** -- Android refuses to install an APK signed with a different key
over an existing app of the same package id. The only remedy is asking
every installed user to manually uninstall and reinstall from scratch
(losing local app data in the process). Back the keystore file up
somewhere durable and private, outside this repo, now -- not after this
happens once.

## 5. Invoicing someone who has no account

In plain terms (full detail: `docs/design/17-contact-users-and-email-verification.md`):

You can create and send an invoice to any email address, even if that
person has never signed up. This creates a `users` row for them in a
special **contact** state -- addressable (the invoice is really attached
to them, mail can be sent to them) but not a real account: it has no
password, and nothing can log in as it.

When that person later registers with the same email, they don't "link"
or "claim" an invoice through some separate step -- their existing row is
upgraded in place from contact to a real account once they click the
verification link and prove they control that inbox. The invoice was
already theirs the whole time.

**They cannot see or pay the invoice until they verify.** This is
deliberate: without requiring inbox proof, anyone could register
`someone-else@example.com`, "claim" that person's invoices, and read
their billing history, amounts, and payment records. Whoever proves they
control the inbox is the only one who can ever see what was invoiced to
that address -- there's no in-between state where linkage alone is
enough.

Practical consequence for you as the person invoicing: if a customer
says "I can't see my invoice after creating an account," the very first
question is "did you click the verification link in your email?" -- not
a bug report.

## 6. Payments

From `domain/payments/providers/`:

| Provider | Required env vars (both) | `is_configured` in |
|---|---|---|
| Stripe | `PAYMENT_PROCESSOR_SECRET` (sk_/secret key) + `STRIPE_PUBLISHABLE_KEY` (pk_) | `stripe_provider.py` |
| PayPal | `PAYPAL_CLIENT_ID` + `PAYPAL_CLIENT_SECRET` | `paypal.py` |

Both providers require **both** halves of their pair -- e.g. a Stripe
publishable key alone is not enough, because the button would show but
every actual charge attempt would fail server-side with no secret key to
mint a PaymentIntent. Each provider's "Pay with X" button is **hidden**,
not shown-then-broken, whenever its `is_configured()` check fails.

If neither is configured (or a customer prefers not to use them), the pay
page always shows manual fallback methods instead: a Zelle handle
(`payment_methods.zelle_handle`) and/or a PayPal-direct receive email
(`payment_methods.paypal_receive_email`), whichever is actually set --
see `frontend/src/app/routes/customer/Pay.tsx`. There's also a "mark as
paid manually" admin action for recording a Zelle/in-person/PayPal-direct
payment the system itself never processed.

## 7. Common failures and what to do

| Symptom | Cause | Fix |
|---|---|---|
| CI red on `system-tests` | This job runs `docker compose -f docker-compose.test.yml up -d --build`, which brings up postgres/redis/mailpit and runs `pytest tests/system` against it. mailpit is what lets the email-verification system test actually receive mail. A stack-startup failure, a schema mismatch, or a mail-flow regression shows up here, not in `backend`'s unit/integration job. | `gh run view <run-id> --log-failed`, reproduce locally: `docker compose -f docker-compose.test.yml up -d --build && cd backend && uv run pytest tests/system -n auto`. |
| Deploy aborted: "CI did not pass cleanly for this SHA" | `wait-for-ci` in deploy.yml saw a non-success conclusion on `backend`/`frontend`/`wasm-ascii`/`system-tests` for this exact commit. | `gh run list --workflow=ci.yml` for the same SHA, find which job failed, fix it, push again (a new push re-triggers both workflows). |
| `alembic upgrade head` fails on deploy, or the `migrate` container exits nonzero | Two migration heads (see section 2), or a migration that's syntactically broken/never tested against real Postgres. | `cd backend && uv run alembic heads` -- if more than one line, fix the fork (re-point one migration's `down_revision`). Test the migration by hand with testcontainers before pushing again. |
| Android build failing with a source directory missing from the built APK, or Gradle acting like a package doesn't exist | An unanchored `.gitignore` pattern (e.g. a bare `logs/` with no leading slash) matches a directory of that name at ANY depth in the tree -- this actually swallowed `android/app/src/main/kotlin/.../ui/admin/logs/`, a real source package, not a log directory. | Check `.gitignore` for unanchored patterns; anchor them with a leading slash (`/backend/logs/`, `/logs/`) so they only match at the repo root, not everywhere. |
| New user registers, never gets a verification email, can't log in | Mail misconfigured or transiently failing -- see section 3. | Check config booleans (section 3), have them call `resend-verification`, or fix `GMAIL_SERVICE_ACCOUNT_JSON`/`GMAIL_SENDER_EMAIL` in `backend/.env` and restart the backend container. |
| "exec: uv: executable file not found" from the `scheduler` container | The final Dockerfile stage doesn't have `uv` installed (only the discarded build stage does) -- a command that starts with `uv run ...` in `docker-compose.yml` fails immediately. | Commands for `backend`/`migrate`/`scheduler` services must NOT be prefixed with `uv run` -- `PATH` already points at `/app/.venv/bin` directly (e.g. `alembic upgrade head`, `python -m logand_backend.scripts.scheduler`). |

## 8. Pre-push checklist

Run all four toolchains' checks before pushing to `main` (CI runs these
too, but catching it locally is faster than waiting 10+ minutes for CI to
tell you):

```bash
# Backend
cd backend
uv run ruff check src/ tests/
uv run ty check src/              # this project uses ty, NOT mypy
uv run pytest tests/unit tests/integration tests/system -n auto
uv run alembic heads              # must print exactly ONE line

# Frontend
cd ../frontend
npx tsc --noEmit
npx eslint .
npx vitest run

# Android (only if android/ changed -- it's excluded from ci.yml/deploy.yml)
cd ../android
./gradlew :core:test :app:testDebugUnitTest
```

`tests/system` needs the Docker test stack up first:
`docker compose -f docker-compose.test.yml up -d --build` from the repo
root (see the `system-tests` CI job for the exact incantation this
mirrors). `backend/Makefile`'s own `make test` target only runs
`tests/unit tests/integration` (fast, no Docker needed) -- use `make
test-system` (`uv run pytest tests/system -n auto`) for the rest, or the
combined `make check` (`lint typecheck test` plus `frob check`), which
still does not include `tests/system` on its own.
