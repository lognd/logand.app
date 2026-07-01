# logand.app

Personal + professional site and protected admin tool for Logan Dapp
(`logand.app` / `logandapp.com`). Public landing/projects/contact pages
plus an internal invoicing, budget, and inventory system behind auth --
including multi-method invoice payments (Stripe, PayPal, and manually-
recorded Zelle/in-person payments), professional PDF invoice generation,
and row-level-locked payment operations so the same invoice can never
be double-charged or double-recorded under concurrent requests.

Full product spec and architecture: **[docs/design/](docs/design/README.md)**
-- start there, not here, for anything about *what* to build or *why*.
Deploying this yourself? Start at **[docs/deployment.md](docs/deployment.md)**
instead. Using the deployed site? See **[docs/usage.md](docs/usage.md)**.
This file only covers *how to run the repo*. See
**[docs/README.md](docs/README.md)** for the full documentation index.

<!-- NOTE(logan): keep this file short. If you're about to explain a
     design decision here, it belongs in docs/design/ instead -- link
     to it, don't restate it. -->

## Layout

```
backend/      Python / FastAPI / pydantic / typani -- see docs/design/01
frontend/     TypeScript / React / Tailwind -- see docs/design/07
wasm-ascii/   Rust crate, ASCII rasterizer -- see docs/design/08
ops/          VPS-side tooling (backups, release-watch) -- see below
docs/design/  pre-implementation specs, read by component
docs/         deployment/secrets/usage guides + runbooks -- see docs/README.md
.github/      CI (every PR) + deploy (push to main)
```

Each of `backend/`, `frontend/`, `wasm-ascii/` is independently
buildable via its own `Makefile`. The root `Makefile` composes them.

## Quick start

```bash
docker compose -f docker-compose.dev.yml up -d   # postgres + redis only
cp backend/.env.example backend/.env              # fill in real values, never commit
make install
make migrate -C backend                            # or: make -C backend migrate
make check                                          # lint + typecheck + tests, every subproject
```

Backend dev server: `cd backend && uv run logand-backend` (or your
IDE's run config against `src/logand_backend/__main__.py`).
Frontend dev server: `cd frontend && npm run dev`.

## Testing

`make test` runs unit + integration for every subproject. `make
test-system` brings up `docker-compose.test.yml` and runs the full
end-to-end suite (backend `httpx` system tests + Playwright). Every
component is required to carry all three layers -- see
[docs/design/12-testing-strategy.md](docs/design/12-testing-strategy.md)
for what belongs in which layer before adding a test.

## CI/CD

- `.github/workflows/ci.yml` -- runs on every PR and push to `main`:
  lint + typecheck + unit/integration per subproject, then a combined
  system-test job against `docker-compose.test.yml`.
- `.github/workflows/deploy.yml` -- on push to `main`, after CI passes:
  builds images, pushes to GHCR, ships the frontend build + restarts
  the backend on the VPS over SSH.
- `ops/release_watch/` -- a small pull-based fallback: a systemd timer
  on the VPS polls the GitHub releases API and redeploys if it's behind
  the latest tag, in case a push deploy fails partway. Not a
  replacement for `deploy.yml`, a safety net for it.

<!-- NOTE(logan): deploy.yml's wait-for-ci job polls the GitHub checks
     API for this SHA rather than using workflow_run, because
     workflow_run's "same SHA" semantics get subtle fast. If GitHub
     ships a cleaner native "wait for sibling workflow" primitive,
     switch to it and delete the polling job. -->

<!-- NOTE(logan): backend/src/logand_backend/db/models/inventory.py's
     full-text-search tsvector column is NOT expressible as a plain
     SQLAlchemy mapped_column -- it needs a hand-written Alembic
     migration (generated column + GIN index). Don't expect
     `alembic revision --autogenerate` to produce it correctly. -->

<!-- NOTE(logan): the wasm-ascii pkg/ output only exists after
     `make -C wasm-ascii build` has run once -- frontend/src/ascii's
     dynamic import of it will 404 on a fresh checkout until then.
     `make build` at the root runs them in the right order; `make
     install` alone does not build wasm-ascii. -->

## Secrets

Never commit `.env`. Real values go in `backend/.env` (gitignored) and
in GitHub Actions repo secrets. No agent working in this repo should
ever read `.env` directly or indirectly -- see
[docs/design/00-overview.md](docs/design/00-overview.md) and
[docs/design/02-auth-and-security.md](docs/design/02-auth-and-security.md).
For what every individual secret is and how to rotate it, see
**[docs/secrets.md](docs/secrets.md)**.

## License

[MIT](LICENSE) -- use, modify, and redistribute freely, with
attribution (see the license file for the exact terms). This is a
personal project shared in case any of it (the ASCII renderer, the
LaTeX invoice PDFs, the payment-provider abstraction) is useful to
someone else, not a maintained product -- expect to fork and adapt
rather than file issues against it.
