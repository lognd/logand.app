# scripts/prodtest -- black-box production test harness

Exercises the real, running production site (`https://logand.app` by
default) exactly the way a real user/admin would: real HTTPS requests
against the public domain, real cookies, real CSRF tokens, real file
uploads, plus SSH into the VPS (`ops/setup-vps.sh`'s host) for two things
only -- confirming an uploaded file is actually gone from disk after a
probe cleans up, and a last-resort raw-SQL row delete for the handful of
tables that have no delete route at all (see below).

**This is not `backend/tests/system/` run against a different URL.**
Those tests spin up an isolated app instance and a disposable test
Postgres; this suite runs against the one real database backing the real
site, so its entire design center is: *never leave anything behind.*

## The zero-artifacts guarantee

Every probe is a `Probe` subclass (`revert.py`) with two methods:

- `check_capability(env)` -- return `True` if this probe can run right
  now, or a string skip-reason (e.g. a feature this deployment doesn't
  have wired up yet -- see `auth_flow.py`'s `SessionKillAllProbe`).
- `execute(env, cleanup)` -- do the real thing. Every mutating call is
  immediately followed by `cleanup.defer(description, revert_fn)`,
  *before* the next mutating call runs -- so if `execute()` raises
  halfway through, only the mutations that actually happened get
  reverted (never a revert for something that never ran, never a
  missing revert for something that did).

The runner (`runner.py::run_probe`) always calls `cleanup.close()` in a
`finally`, regardless of whether `execute()` raised, and always runs
*every* deferred revert even if an earlier one in the stack raised --
one broken revert must never stop the rest of the cleanup. If **any**
revert fails, the probe is reported `FAIL` with `CLEANUP FAILED --
POSSIBLE PRODUCTION ARTIFACTS LEFT BEHIND` **even if every assertion in
`execute()` passed** -- a clean revert is treated as no less important
than the behavior under test.

`scripts/prodtest/tests/test_revert_guarantee.py` is a pure-unit-test
proof of this mechanism (no network at all) -- reverse-order execution,
survival of a failing revert, partial-mutation-only-partial-revert, and
the "assertions passed but cleanup failed -> still FAIL" case. **This is
the one part of this directory that runs in CI** (see ci.yml's
`prodtest-self-test` job) -- the probes themselves never do; see below.

## Why some cleanups need SSH, not just the API

Two real facts about this codebase's design that this harness has to
work around, not paper over:

1. **Some tables have no delete route at all**, by design (invoices and
   budget entries are meant to be an append-only audit trail --
   corrections, not deletions; inventory locations just never got a
   delete endpoint). For these, cleanup uses the real
   `/api/admin/data/tables/{table}/rows/{id}` generic admin route
   (`admin_data_helper.py`) -- a real, audited, already-shipped admin
   capability, not a raw SQL bypass. It does write one permanent
   `admin_audit_log` row per delete; that's the audit log doing exactly
   its job (see `service.py`'s own comment on why this tool can't erase
   its own trail), not an artifact this harness failed to clean up.
2. **`delete_document`/`delete_receipt` are soft-deletes** (`deleted_at`
   set) that never touch the storage backend at all. A probe that
   uploads a file therefore always does three things on cleanup: call
   the real DELETE route (exercising that code path for real), hard-
   delete the row via admin_data, and `ssh` + `docker exec ... rm -f`
   the actual file on disk -- then verifies via `docker exec ... test -e`
   that it's actually gone. `budget.py`'s evidence-upload route has no
   delete concept whatsoever, so its probe does the same file removal by
   hand.

`ssh_client.py`'s `VpsSsh` is intentionally narrow: `run()` for a
trusted, harness-authored command string, `docker_exec()` with each
argument individually shell-quoted, and `psql_delete_row()` which
rejects any table/column name that isn't a plain alphanumeric identifier
before it ever reaches a query (the row id itself goes through psql's
own `-v`/`:'var'` substitution, not string interpolation). It is not a
general "run whatever" wrapper.

## Payment provider / notification probes

Three probes specifically verify the Stripe and SMTP credentials
actually work once you've filled them into `backend/.env`
(`payment_provider_health.py`, `notification_flow.py`):

- **`StripeLiveCredentialsProbe`** -- SSH + runs the backend's own
  `python -m logand_backend.scripts.health_check` in the deployed
  container and requires its report to say
  `stripe: credentials valid (live mode)`. Zero mutation: that check is
  a single read-only `stripe.Balance.retrieve()` call, nothing is
  created or charged. This is the right probe for "did I actually put a
  real `sk_live_...` key in, and does Stripe accept it."
- **`SmtpReachabilityProbe`** -- same mechanism, requires the report to
  show `SMTP_HOST:PORT` reachable and `MAILING_ADDRESS` set. Zero
  mutation: a raw TCP connect, no message sent, no auth attempted.
- **`InvoiceNotificationEmailProbe`** -- the one probe that actually
  authenticates against real SMTP credentials and sends real mail: it
  creates a throwaway customer at `PRODTEST_NOTIFICATION_EMAIL`
  (default `prodtest@logand.app`, configurable in `.env` -- see
  `.env.example`), sends them an invoice and records a manual payment
  against it (firing `notify_invoice_sent`/`notify_payment_received`
  for real), then tails `/api/admin/logs/tail` to confirm neither send
  was logged as failed. `mailer.send_email()` swallows send failures by
  design (email is best-effort, see `notify.py`), so "no error logged"
  is the strongest automatable proof available without giving this
  harness IMAP access to actually read the inbox -- the probe prints the
  real destination address it used so you can glance at that inbox
  yourself to finish confirming delivery/content. Cleanup follows the
  exact same proven FK-order as `invoice_flow.py`'s
  `InvoiceLifecycleProbe` (payment, then invoice, then customer).

## Running it

```bash
cp scripts/prodtest/.env.example scripts/prodtest/.env
# fill in PRODTEST_ADMIN_EMAIL/PASSWORD with a real admin account on prod
# (NOT the SEED_ADMIN_* bootstrap pair -- see docs/deployment.md; that
# pair should not be sitting in backend/.env at all past first bootstrap)

cd backend && uv run python -m ../scripts/prodtest/cli
# or, from repo root, with backend's venv active:
#   python -m scripts.prodtest.cli
```

Prints one line per probe (`PASS`/`FAIL`/`SKIP`), a detail block under
any non-PASS, and a final tally. Non-zero exit on any `FAIL`.

## Never run automatically

`cli.py` (and everything under `probes/`) is not referenced anywhere in
`.github/workflows/*.yml`, and never should be -- it makes real writes
against the real production database and a real customer-facing
domain, and a bug in it is a bug against prod, not a disposable CI
container. Run it by hand when you want live confidence that the
deployed site actually works, not on every push. `tests/` (the harness's
own correctness tests) is the only part of this directory CI touches.

## Adding a new probe

1. Subclass `Probe` in a new (or existing) file under `probes/`.
2. Every mutating HTTP call gets a `cleanup.defer(...)` in the same
   breath -- write the revert right next to the action that needs it,
   not batched at the end of `execute()`.
3. If the entity type has no delete route, use `admin_data_helper.py`'s
   `hard_delete_row`/`row_exists`, respecting FK order (defer child-row
   cleanup *after* parent-row cleanup in the source, so LIFO reverts the
   child first -- see `invoice_flow.py`'s comment on this).
4. If the probe uploads a file, remove it from disk via
   `env.ssh.docker_exec(...)` and verify with
   `env.ssh.file_exists_in_container(...)` returning `False`.
5. Register the new probe instance in `probes/__init__.py`'s
   `ALL_PROBES`.
6. If the probe exercises a route/feature that isn't always present in
   every deployment (e.g. PayPal, R2 storage, a Redis-backed feature),
   check for it in `check_capability()` and return a skip string rather
   than letting `execute()` fail confusingly.
