# Design Docs Index -- logand.app

This is the entry point for design documentation. Each document below is
self-contained: an agent assigned to a task should read **only** the
document(s) relevant to that task, not the whole set.

Source of truth for product intent: `/README.md` (repo root). These docs
translate that intent into concrete, buildable specs. If a doc and the
root README conflict, the root README's intent wins -- file a note in
the doc and ask the human, don't silently pick one.

## Reading map (find your task, read only those docs)

| If you are building...                          | Read |
|---------------------------------------------------|------|
| The Python backend skeleton, app structure, FastAPI wiring | [01-backend-architecture.md](01-backend-architecture.md) |
| Login, sessions, rate limiting, password storage, CSRF | [02-auth-and-security.md](02-auth-and-security.md) |
| Database schema, migrations, ORM models | [03-database.md](03-database.md) |
| The invoicing feature (admin + customer endpoints) | [04-invoices.md](04-invoices.md) |
| The budget / expense-ledger feature | [05-budget.md](05-budget.md) |
| The personal inventory feature | [06-inventory.md](06-inventory.md) |
| The TypeScript/Tailwind frontend app shell | [07-frontend-architecture.md](07-frontend-architecture.md) |
| The Rust/WASM ASCII rasterizer | [08-ascii-wasm-renderer.md](08-ascii-wasm-renderer.md) |
| Visual design, typography, color, motion, accessibility | [09-design-system.md](09-design-system.md) |
| SEO, structured data, AI-agent accessibility | [10-seo-and-agent-accessibility.md](10-seo-and-agent-accessibility.md) |
| Docker Compose, VPS deployment, CI/CD | [11-deployment.md](11-deployment.md) |
| Unit/integration/system tests for any component | [12-testing-strategy.md](12-testing-strategy.md) |

**Every component is required to have unit, integration, and end-to-end
system tests -- backend and frontend both.** [12-testing-strategy.md](12-testing-strategy.md)
is not optional reading; every feature doc above links into it for its
specific test obligations.

[00-overview.md](00-overview.md) is the only doc every agent should skim
first -- it has the repo layout and cross-cutting decisions everything
else assumes.

## Status

All docs in this set are **design-stage**, written before any
implementation exists. They record decisions, not yet-built reality.
When implementation diverges from a doc (it will), update the doc in
the same PR as the code change -- do not let them drift.

## Locked decisions (do not re-litigate without asking the human)

- Database: **PostgreSQL**.
- Repo layout: **monorepo**, top-level `backend/`, `frontend/`, `wasm-ascii/`.
- Auth: **server-side session cookies** (HttpOnly, Secure, SameSite), not JWT.
- Deployment: **single VPS via Docker Compose**.

See [00-overview.md](00-overview.md) for the reasoning behind each.
