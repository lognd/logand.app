# 15 -- Admin Tools and Observability

Audience: anyone touching the generic admin data browser
(`domain/admin_data/`), the shared audit log (`AdminAuditLog`), or any
of the logging systems (backend, frontend, Android). Read
[00-overview.md](00-overview.md) first.

## Why this exists

Two related but distinct requirements drove this doc:

1. **"Absolute power, but never a corrupt state."** The admin needs a
   way to fix one-off data problems in any table without a raw DB
   client, but every write must still be validated, confirmed, and
   reversible.
2. **"If anything ever crashes, I want to be able to find exactly what
   happened through the logs."** Every platform (backend, frontend,
   Android) needs centralized, bounded, retrievable logging -- not
   scattered `print()`/`console.log` calls that vanish when a tab
   closes or a container restarts.

## Admin data browser (`domain/admin_data/`, `api/admin_data.py`)

Generic, reflection-based CRUD over `Base.metadata.tables` (SQLAlchemy
Core `select`/`update`/`delete`/`insert`, never raw SQL string
interpolation) -- genuinely any table, not a hand-maintained per-table
allowlist. Every write still passes through Postgres's own FK/check/
unique/not-null constraints, which is what structurally guarantees "no
corrupt state": a constraint violation aborts the whole write atomically.

Two deliberate exceptions to "any table, any column":

- The `sessions` table is excluded entirely -- a session row is a live
  authentication credential, not business data; hand-editing or forging
  one is a security bypass, not a data correction.
- `password_hash` is never directly editable on any table -- a raw
  string there isn't a valid hash, so the account becomes permanently
  unable to log in even though nothing about that write violates a DB
  constraint. Real password resets go through
  `domain/users/service.py::admin_reset_password`, which hashes
  properly.

### Rollback: `AdminAuditLog`

Every insert/update/delete (from the data browser AND from
`domain/users/service.py`'s customer-account actions) writes a full
before/after JSON snapshot to one shared `admin_audit_log` table.
`revert_change` replays a logged entry backwards through the SAME
validated write path it came from (an update reverts via another
update, a delete reverts via a re-insert, an insert reverts via a
delete) -- never a raw restore, so a revert is exactly as
constraint-safe as the original write was.

The admin UI requires an explicit confirm step showing the exact
before-to-after diff before any write fires -- the same convention
applied to every other risky admin action on this site (inventory
adjustments, customer deactivation, BOM stock consumption).

## Logging

One requirement, three platforms, each satisfying it the way that
platform actually works.

### Backend (`logand_backend/logging/`)

- `logger.py` / `config.toml`: stdlib `dictConfig`, three handlers --
  `stdout` (DEBUG/INFO, human-readable), `stderr` (WARNING+), and
  `file` (DEBUG+, one JSON object per line via `json_formatter.py`).
- `handler.py`'s `SizeCappedTimedRotatingFileHandler`: one file per UTC
  day (`TimedRotatingFileHandler`), PLUS a size-forced mid-day rollover
  so a burst of error logging can't grow a single day's file unbounded
  between midnight rotations.
- `retention.py`'s `prune_logs`: exponential-backoff retention on the
  rotated files -- every day for the last week, then one per week for
  the next couple months, then one per month beyond that -- plus a hard
  total-size backstop regardless of the schedule. Run daily by
  `scripts/scheduler.py` (the same container that generates recurring
  invoices).
- `request_context.py`: a per-request id (contextvar), set by
  `app/app.py`'s outermost middleware, attached to every log line via
  `RequestIdFilter` -- ties one request's access log line to every
  error logged deeper in the same call stack, and to whatever request
  id a frontend crash report hands back (see `x-request-id` response
  header, read by `frontend/src/api/client.ts`).
- **Unhandled exceptions are caught in the middleware itself, not via
  `app.add_exception_handler(Exception, ...)`** -- Starlette's
  `BaseHTTPMiddleware` (what `app.middleware("http")` uses) has a
  long-standing limitation where an exception raised past `call_next`
  does not reach handlers registered that way; confirmed by a real test
  that failed until the catch was moved into the middleware directly.
- `api/admin_logs.py`: admin-only list/tail/download of real log files,
  no shell access to the VPS needed.

Where logs live: `LOG_DIR` (default `./logs`), a real named Docker
volume shared between the `backend` and `scheduler` services -- see
`docs/secrets.md`'s `LOG_DIR` entry.

### Frontend (`frontend/src/lib/logging.ts`)

A bounded ring buffer (max 500 entries, oldest dropped first), mirrored
into `localStorage` so entries survive a reload. Captures:

- `window.onerror` / `unhandledrejection` (installed once, in
  `main.tsx`, before the first render).
- React render crashes, via a top-level `ErrorBoundary`
  (`app/layout/ErrorBoundary.tsx`) wrapping `<App/>`.
- Every failed API request (`api/client.ts`), logged with the backend's
  `x-request-id` so a client-side log entry and the matching backend
  log line can be correlated.

Two UI surfaces read from it: an always-visible "Report a problem"
button (`app/layout/ReportProblemButton.tsx`, present on every page,
not just after a crash) and the `ErrorBoundary`'s own crash screen --
both download a plain-text export a user can send along with a bug
report. `app/routes/admin/AdminLogs.tsx` is the read-only admin
counterpart for real backend log files (list/tail/download, wraps
`api/admin_logs.py`).

### Android (`core/.../logging/FileLogger.kt`)

Pure `java.io.File`-based (no Android imports, lives in `:core` so it's
a plain JVM unit test, not an instrumented one) -- a size-capped,
generational rotating log (`app.log`, `app.log.1`, `app.log.2`, ...,
oldest beyond the cap dropped). No calendar-bucketed exponential
retention here, unlike the backend: a single phone generates a tiny
fraction of a server's log volume, so a flat file-count cap is the
right-sized "never overflow" guarantee for this platform.

`app/.../logging/CrashHandler.kt` installs itself as
`Thread.setDefaultUncaughtExceptionHandler`, logs the full stack trace,
then hands off to whatever handler was already installed (never
swallows the crash or tries to keep the app running in a broken state).
`app/.../logging/ShareLogsAction.kt` opens the system share sheet with
every log file concatenated -- reachable from the login screen
regardless of session state ("Share app logs"), reusing the same
`FileProvider` authority already declared for receipt-photo capture.

## Version/environment introspection (`api/admin_version.py`)

`GET /api/admin/version` (admin-only) answers "what is actually running
on this server right now" without shelling in: the app's own version
(`pyproject.toml`, read via `importlib.metadata`), the deployed git
commit (baked into the Docker image at build time -- see `Dockerfile`'s
`GIT_COMMIT` build arg and `.github/workflows/deploy.yml`, which passes
`--build-arg GIT_COMMIT=${{ github.sha }}`; there is no `.git` directory
in the built image to introspect at runtime instead), the Python
version, and the real, currently-installed version of every single
dependency (`importlib.metadata.distributions()` -- reflects what's
actually resolved in this environment, not a static re-read of
`pyproject.toml`/`uv.lock`, so it stays correct even after a lockfile
update this endpoint's own code was never touched for).

## Testing

- `domain/admin_data/service.py`: integration tests cover every write
  path (update/delete/insert/revert), the `password_hash`/`id`
  exclusions, and a real Postgres constraint-violation round trip
  (`tests/integration/test_admin_data_service.py`).
- `api/admin_data.py` / `api/admin_logs.py`: system tests cover
  auth-gating, the full update -> list-changes -> revert round trip,
  and path-traversal rejection on log file downloads
  (`tests/system/test_admin_data_api.py`, `tests/system/test_admin_logs_api.py`).
- `logging/retention.py`: pure-function unit tests on real files under
  `tmp_path` -- daily/weekly/monthly bucketing, the hard-cap backstop,
  and same-day multi-rotation bucketing (`tests/unit/test_log_retention.py`).
- `logging/handler.py`: unit tests confirm size-forced rotation and
  that the handler never self-deletes rotated files
  (`tests/unit/test_log_handler.py`).
- `app/app.py`'s request-id/exception-logging middleware: a system test
  forces a real unhandled exception and asserts the resulting log entry
  contains the full traceback plus the same request id returned in the
  response header (`tests/system/test_request_logging.py`).
- Frontend: `lib/logging.ts` (ring-buffer bound, persistence, export
  formatting), `ErrorBoundary` (a real thrown-in-render crash), and
  `AdminLogs.tsx` (list/tail/download UI) each have real
  `tests/unit/*.test.ts(x)` coverage.
- Android: `FileLoggerTest` (`:core`) covers rotation and the backup-
  count cap as real JVM tests, no emulator required.
