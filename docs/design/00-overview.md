# 00 -- Overview & Repo Layout

Read this first, always. It is the only doc with cross-cutting context.
Everything else assumes you already know what's here.

## What this project is

`logand.app` (alias `logandapp.com`) is Logan Dapp's personal/professional
site. It is two things at once:

1. A **public-facing site**: landing page, projects, contact info,
   optimized for both human visitors and AI/web-crawler agents.
2. A **protected internal admin tool**: invoicing, budget/expense
   ledger, personal inventory tracking -- all behind auth, with a
   secondary customer-facing surface for invoice payment.

Guiding mantra from the root README: **safety first, admin has absolute
power**. Concretely: rate-limiting, hashed+salted secrets, no plaintext
sensitive data, real session management -- but the admin (Logan) account
is never artificially constrained by the permission model that protects
everyone else.

## Locked architectural decisions

These were decided with the human up front. Do not reopen them inside a
design doc -- if a doc seems to need a different answer, stop and ask.

| Decision | Choice | Why |
|---|---|---|
| Database | PostgreSQL | Invoicing/budget data needs audit-grade integrity, constraints, and concurrent-write safety that SQLite doesn't comfortably give. |
| Repo layout | Monorepo, top-level `backend/`, `frontend/`, `wasm-ascii/` | Three different toolchains (Python, TS, Rust) are cleaner as siblings than interleaved in one `src/`. |
| Auth | Server-side session cookies (HttpOnly, Secure, SameSite=Strict) + DB-backed session store | Instant revocation ("absolute admin power" includes the power to kill any session immediately), simpler threat model than JWT rotation for a low-traffic site. |
| Deployment | Single VPS, Docker Compose | Matches "I want full control over my own infrastructure"; no managed-service vendor lock-in. |

## Repo layout

```
logand.app/
  backend/                   # Python, FastAPI + pydantic + typani
    src/logand_backend/
      app/                   # App / AppConfig pattern (see 01)
      api/                   # FastAPI routers, one module per feature
      domain/                # pydantic models, business logic
      db/                    # SQLAlchemy models, migrations (alembic)
      auth/                  # sessions, password hashing, rate limiting
      logging/               # standard logging module (see ~/.claude/refs/logging.md)
    tests/
      unit/
      integration/
      system/
    pyproject.toml
    Makefile

  frontend/                  # TypeScript + Tailwind CSS
    src/
      app/                   # routes / pages
      components/
      ascii/                 # wasm-ascii bindings + JS/CSS fallback renderer
      styles/
    public/
    package.json
    Makefile

  wasm-ascii/                 # Rust crate compiled to WASM
    src/
    Cargo.toml
    Makefile

  docs/
    design/                  # this directory -- pre-implementation specs
    (post-implementation docs go in docs/ root, written by the `document` skill)

  .github/workflows/         # CI/CD
  docker-compose.yml
  Makefile                   # root Makefile delegates to backend/frontend/wasm-ascii
```

Each subproject (`backend/`, `frontend/`, `wasm-ascii/`) is independently
buildable and testable via its own Makefile. The root Makefile composes
them (`make check` = all three `make check` targets).

## Cross-cutting non-negotiables

- **Never** read, log, or transmit `.env` contents or values from GitHub
  Actions secrets. Use `python-dotenv` / `import.meta.env` to load, never
  inline real values, even in examples.
- **No plaintext secrets anywhere** -- passwords are hashed (Argon2id),
  API/session tokens are random + hashed at rest, payment processor
  secrets live only in `.env` / CI secrets.
- **Rate limiting** applies to every public-facing endpoint, especially
  auth and the customer invoice-payment surface. Admin endpoints get
  generous limits, not zero limits (a compromised admin session is still
  a risk).
- **TypeScript everywhere on the frontend** -- no plain `.js`.
- Backend: `from __future__ import annotations` as the first line of
  every module, `src/` layout, pydantic v2 (`model_config = {}`, never
  `class Config`), typani `Result`/`Option` for fallible operations.
- Commit format, Makefile-first tooling, and all Python conventions
  follow `~/.claude/refs/python.md`, `~/.claude/refs/pydantic.md`,
  `~/.claude/refs/typani.md`, `~/.claude/refs/frob.md` -- read those at
  the start of any backend coding session.

## Open questions deferred to later docs

Each is owned by exactly one doc, so don't duplicate the decision
elsewhere:

- Session/cookie mechanics, password hashing, CSRF, rate-limit
  thresholds -> [02-auth-and-security.md](02-auth-and-security.md)
- Concrete table schemas -> [03-database.md](03-database.md)
- Payment processor choice for invoices -> [04-invoices.md](04-invoices.md)
- Test strategy (unit/integration/system, both backend and frontend --
  required for every component, no exceptions) ->
  [12-testing-strategy.md](12-testing-strategy.md)
