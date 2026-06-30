# 12 -- Testing Strategy

Audience: every agent building any component of this project. This is a
hard requirement, not optional polish: **every component, backend and
frontend, must have unit tests, integration tests, and end-to-end system
tests.** No feature is "done" without all three layers for the parts of
it that apply. Read [00-overview.md](00-overview.md) first.

## The three layers, defined precisely

- **Unit**: tests one function/class in isolation, no I/O (no real DB,
  no real HTTP, no real filesystem). Fast, runs in milliseconds.
- **Integration**: tests the boundary between two real systems --
  domain code against a real (test) Postgres, or a frontend API-client
  function against a real (test) backend instance. No mocking the thing
  you're actually testing the boundary of.
- **System / end-to-end**: drives the whole stack as a black box --
  real HTTP requests against a running backend for the API surface,
  real browser automation against a running frontend for the UI surface.

A unit test that mocks the database is not a substitute for an
integration test against a real one, and an integration test is not a
substitute for a system test that exercises the actual deployed
contract (HTTP, cookies, CORS, etc.) -- each layer catches a different
class of bug. Don't skip a layer because a lower layer is green.

## Backend

```
backend/tests/
  unit/          # domain/ functions, pure logic, ErrorSet branches, pydantic validators
  integration/   # domain/ + db/ against a real test Postgres (testcontainers or a
                  #   docker-compose.test.yml Postgres service); also auth/ sessions,
                  #   rate limiter, CSRF middleware against real Redis/Postgres
  system/        # full FastAPI app via httpx.AsyncClient against a running app instance
                  #   (or in-process ASGI transport), real cookies, real CSRF flow,
                  #   real Stripe webhook payloads (signed with a test secret)
```

- Framework: `pytest`, `pytest-asyncio` (`asyncio_mode = "auto"`, per
  `~/.claude/refs/python.md`), `pytest-xdist` for parallel runs.
- Test DB: a real Postgres instance (via `testcontainers-python` or the
  `docker-compose.test.yml` service), migrated fresh per test session,
  wrapped in a transaction per test that rolls back -- never tests
  against the dev/prod database, never mocks Postgres in integration
  tests.
- Coverage obligations per feature doc:
  - [02-auth-and-security.md](02-auth-and-security.md): session
    expiry/sliding-window, CSRF rejection on mismatched token,
    rate-limit 429 + `Retry-After`, Argon2id hash/verify round-trip,
    "kill all sessions" actually invalidates every row -- unit +
    integration.
  - [03-database.md](03-database.md): migration up/down round-trips
    cleanly on a fresh DB -- integration, run in CI on every PR that
    touches a migration.
  - [04-invoices.md](04-invoices.md): cross-customer ownership isolation
    (404 not 403), `amount_total` recomputed server-side regardless of
    client input, Stripe webhook idempotency (replay the same event
    twice, state changes once), recurring-invoice generation -- unit
    (recurrence logic) + integration (DB + webhook handler) + system
    (full webhook POST with real signature verification).
  - [05-budget.md](05-budget.md): correction-not-overwrite invariant
    once evidence is attached, evidence file hash matches uploaded
    content -- integration.
  - [06-inventory.md](06-inventory.md): location delete-restrict when
    items reference it, full-text search returns expected matches --
    integration.
- `make test` runs unit + integration; `make test-system` runs system
  tests separately (slower, may need the full Compose stack up) --
  `make check` (see [01-backend-architecture.md](01-backend-architecture.md))
  runs all of it, this is what CI gates on (see
  [11-deployment.md](11-deployment.md)).

## Frontend

```
frontend/tests/
  unit/          # pure functions, hooks in isolation (React Testing Library +
                  #   renderHook), the ASCII luminance-mapping fallback math
  integration/   # components against a real (test) backend instance --
                  #   e.g. the invoice-pay form actually calling a running
                  #   test API and asserting on real responses, not mocked fetch
  system/        # Playwright, real browser, full user flows against the full
                  #   stack (frontend + backend + test Postgres via docker-compose.test.yml)
```

- Unit/component framework: Vitest + React Testing Library.
- Integration: Vitest against a real running backend test instance
  (started via the same `docker-compose.test.yml` used by backend
  integration tests) -- exercises `api/client.ts` and feature API
  modules (see [07-frontend-architecture.md](07-frontend-architecture.md))
  for real, including actual CSRF header attachment and actual 401/429
  handling.
- System: Playwright, headless in CI. Minimum required flows:
  - Public: landing page loads, has real content (not blank SPA shell,
    see [10-seo-and-agent-accessibility.md](10-seo-and-agent-accessibility.md)),
    navigates to projects/contact.
  - Auth: login, wrong password rejected, session persists across
    reload, logout clears session.
  - Customer: log in as a seeded test customer, view own invoices only,
    complete a Stripe test-mode payment, invoice status updates to paid.
  - Admin: log in as admin, create an invoice, create a budget entry
    with evidence upload, create an inventory item, "kill all sessions"
    actually logs the admin out too.
  - Accessibility: automated axe-core scan on every public page as part
    of the system suite, asserting zero critical/serious violations --
    enforces the bar set in
    [09-design-system.md](09-design-system.md).
  - ASCII rendering: WASM path renders without console errors; force
    the `WebAssembly === undefined` fallback path in one test and assert
    it still renders the same visual language (see
    [08-ascii-wasm-renderer.md](08-ascii-wasm-renderer.md)).
- `frontend/Makefile`:
  ```
  test:        vitest run (unit + integration)
  test-system: playwright test
  check:       lint + typecheck + test
  ```
  `make check` is the CI gate for unit+integration; `test-system` runs
  as a separate CI job against the Compose test stack (slower, not
  blocking on every commit if it proves too slow, but required before
  merge to `main`).

## wasm-ascii (Rust)

```
wasm-ascii/
  src/rasterize.rs    # #[cfg(test)] unit tests: known pixel buffer -> known char output
  tests/               # cargo integration tests: wasm-bindgen-test running the
                        #   compiled WASM module in a headless browser (wasm-pack test --headless)
```

This crate's "integration" layer is the WASM-boundary itself (Rust
compiled to WASM, loaded and called from JS exactly as production does)
-- `wasm-pack test --headless --chrome` is the integration test, not a
plain `cargo test` of Rust-only logic (that's the unit layer). The
frontend system suite's ASCII-rendering test (above) is this crate's
true end-to-end coverage, since "the whole system" for a WASM module
means "loaded in a real browser by the real frontend."

## CI gating (cross-reference [11-deployment.md](11-deployment.md))

`ci.yml` runs, per PR, in this order: backend `make check` (unit +
integration), frontend `make check` (unit + integration), `wasm-ascii`
`make check` (unit + wasm-bindgen-test integration), then a single
combined system-test job that brings up the full
`docker-compose.test.yml` stack and runs both backend system tests and
Playwright system tests against it. All four must be green before
merge -- no layer is allowed to regress silently because a faster layer
above it stayed green.
