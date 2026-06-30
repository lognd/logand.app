# 11 -- Deployment

Audience: anyone setting up Docker Compose, the VPS, or CI/CD workflows.
Read [00-overview.md](00-overview.md) first.

## Topology (locked decision: single VPS, Docker Compose)

```
docker-compose.yml
  caddy          # reverse proxy + automatic HTTPS (Let's Encrypt) -- simpler TLS story than nginx+certbot
  backend        # FastAPI app, built from backend/Dockerfile
  frontend       # static build served by caddy directly (no separate frontend container needed
                  #   once prerendered, see 10) -- caddy serves frontend/dist as a file_server block
  postgres       # official postgres image, named volume for data
  redis          # rate limiting (see 02) + can double as a cache later
  backup         # scheduled pg_dump + evidence-volume tarball to off-box storage, see below
```

## Caddy

Caddyfile handles HTTPS automatically (no manual cert management --
matches "full admin control over infra" without taking on cert renewal
toil). Reverse-proxies `/api/*` to the `backend` container,
`/api/webhooks/stripe` included, everything else served as static files
from the frontend build.

## Backend container

`backend/Dockerfile`: multi-stage build, `uv sync --frozen` in a build
stage, final stage copies only the venv + source, runs as non-root user,
`uvicorn` with multiple workers (worker count tied to VPS CPU count, see
sizing below).

## Database

- Official `postgres:16` image, data on a named volume
  (`postgres_data`), never bind-mounted to a host path that could get
  swept up in an unrelated cleanup.
- Migrations (`make migrate`, see
  [01-backend-architecture.md](01-backend-architecture.md)) run as a
  one-shot job before the backend container starts serving traffic (a
  Compose `depends_on` + entrypoint check, or a dedicated `migrate`
  one-shot service run in CI/CD before deploy).

## Backups

- Nightly `pg_dump` of Postgres + tarball of the budget-evidence volume
  (see [05-budget.md](05-budget.md)), both pushed to off-VPS storage
  (e.g. a cheap object storage bucket or a second small VPS used purely
  as a backup target) -- a single-VPS deployment with no off-box backup
  is not "bulletproof for an audit," it's a single point of failure.
- Retention: 30 daily, 12 monthly. Document the restore procedure in
  `docs/runbooks/restore.md` once the backend exists (not a design-time
  artifact, but flag it here so it isn't forgotten).

## VPS sizing (starting point, revisit under real load)

2 vCPU / 4GB RAM minimum -- Argon2id's 64MB memory_cost per concurrent
login attempt (see [02-auth-and-security.md](02-auth-and-security.md))
plus Postgres plus the backend workers fit comfortably; revisit only if
the rate-limiter or monitoring shows real memory pressure.

## CI/CD (`.github/workflows/`)

- `ci.yml`: on every PR -- runs `make check` for `backend/`,
  `frontend/`, and `wasm-ascii/` (lint + typecheck + full test pyramid,
  see [12-testing-strategy.md](12-testing-strategy.md)). Must be green
  before merge.
- `deploy.yml`: on push to `main` after CI passes -- builds and pushes
  Docker images to a registry (GitHub Container Registry, no extra
  account needed), SSHes to the VPS, runs `docker compose pull && docker
  compose up -d`, then the one-shot migration job.
- Secrets (`VPS_SSH_KEY`, `DATABASE_URL`, `SESSION_SECRET`,
  `PAYMENT_PROCESSOR_SECRET`, `STRIPE_WEBHOOK_SECRET`) live in GitHub
  Actions repo secrets, referenced as `${{ secrets.X }}` in workflow
  YAML, **never** echoed or logged -- per the hard rule in
  [00-overview.md](00-overview.md), agents authoring these workflows
  never read or print actual secret values.

## Local development

`docker-compose.dev.yml` overlay: Postgres + Redis only, backend and
frontend run natively via their own Makefiles (`make install && make
dev` equivalent) with hot reload -- containerizing the app code itself
during dev adds friction without benefit.
