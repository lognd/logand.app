# 01 -- Backend Architecture

Audience: anyone building the Python backend skeleton, wiring FastAPI, or
adding a new backend module. Read [00-overview.md](00-overview.md) first
for repo layout. Read `~/.claude/refs/python.md`, `~/.claude/refs/pydantic.md`,
`~/.claude/refs/typani.md`, `~/.claude/refs/python-app.md` before writing
code -- this doc assumes those conventions, it doesn't restate them.

## Stack

- **Framework**: FastAPI
- **Validation/serialization**: pydantic v2
- **Error handling**: typani (`Result`, `Option`, `ErrorSet`) for fallible
  domain operations; FastAPI exception handlers translate `Err` ->
  HTTP responses at the API boundary only.
- **ORM**: SQLAlchemy 2.x (async) against PostgreSQL (see
  [03-database.md](03-database.md))
- **Migrations**: Alembic
- **Package manager**: `uv`

## Directory structure

```
backend/src/logand_backend/
  __main__.py            # entry point, App(cfg)() -- see python-app.md pattern
  app/
    app.py                # App class: owns FastAPI instance, lifespan, router mounting
    config.py              # AppConfig(BaseModel), from_external()
  api/                    # one router module per feature, thin -- no business logic
    auth.py
    invoices.py
    invoices_public.py     # customer-facing invoice payment endpoints
    budget.py
    inventory.py
    health.py
  domain/                  # business logic + pydantic schemas, framework-agnostic
    invoices/
    budget/
    inventory/
    auth/
  db/
    base.py                # SQLAlchemy declarative base, session factory
    models/                 # one file per table group
    migrations/              # alembic
  auth/
    sessions.py             # session create/validate/revoke
    passwords.py             # Argon2id hash/verify
    rate_limit.py             # rate limiter (see 02)
    csrf.py
  logging/                  # see ~/.claude/refs/logging.md, copy that module layout verbatim
  errors.py                 # ErrorSet definitions shared across domain modules
```

## Layering rule

`api/` routers call into `domain/` functions and never touch `db/`
directly. `domain/` functions call into `db/` and never import FastAPI.
This keeps domain logic testable without spinning up HTTP (see
[12-testing-strategy.md](12-testing-strategy.md) for how this layering
maps to integration vs. unit tests).

## App / Config pattern

Follow `~/.claude/refs/python-app.md` exactly:

```python
# __main__.py
def main() -> None:
    args = _build_parser().parse_args()
    cfg = AppConfig.from_external(args, Path("pyproject.toml"))
    App(cfg)()

if __name__ == "__main__":
    main()
```

`AppConfig.from_external` merge priority: CLI args > env vars (loaded via
`python-dotenv`, never read `.env` directly) > TOML defaults > field
defaults. Required env vars: `DATABASE_URL`, `SESSION_SECRET`,
`PAYMENT_PROCESSOR_SECRET` (see [04-invoices.md](04-invoices.md)) -- all
placeholders in examples (`postgresql+asyncpg://user:changeme@host/db`),
never real values.

## Error handling at the API boundary

Domain functions return `Result[T, ErrorSet]`. Routers unwrap:

```python
result = await create_invoice(payload)
if result.is_err:
    raise to_http_exception(result.danger_err)
return result.danger_ok
```

`to_http_exception` is a single shared mapping function
(`api/errors.py`) from `ErrorSet` members to `(status_code, detail)`.
Never let a raw exception escape a router -- every domain `ErrorSet`
variant must have a mapping or the mapping function raises
`NotImplementedError` at import time (fail fast, not at request time).

## Makefile (backend/Makefile)

Follows the standard frob-project format from `~/.claude/refs/python.md`
verbatim (`install`, `test`, `test-fast`, `lint`, `fmt`, `typecheck`,
`check`, `bump`, `clean`). Add one target:

```makefile
migrate:
	uv run alembic upgrade head
```

## What NOT to put here

- Visual/design decisions -> [09-design-system.md](09-design-system.md)
- Schema details -> [03-database.md](03-database.md)
- Auth mechanics -> [02-auth-and-security.md](02-auth-and-security.md)
- Test strategy -> [12-testing-strategy.md](12-testing-strategy.md)
