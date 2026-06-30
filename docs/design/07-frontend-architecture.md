# 07 -- Frontend Architecture

Audience: anyone building the TypeScript/Tailwind frontend app shell,
routing, or API client. Read [00-overview.md](00-overview.md) first.
For visual/aesthetic decisions, see
[09-design-system.md](09-design-system.md) -- this doc is structure
only, not look-and-feel.

## Stack

- **Framework**: React 18 + Vite. The root README references "Motion
  library for React when available," which presupposes React.
- **Language**: TypeScript, strict mode, no plain `.js`/`.jsx` files.
- **Styling**: Tailwind CSS, with CSS variables for theme tokens (see
  [09](09-design-system.md)) layered on top of Tailwind's config.
- **Routing**: React Router.
- **Server state**: TanStack Query (React Query) -- the backend is a
  classic REST+session API, not GraphQL; Query's cache + refetch model
  fits directly.
- **Forms**: React Hook Form + zod for client-side validation, mirroring
  (not replacing) the backend's pydantic validation.
- **Animation**: Motion (formerly Framer Motion) for React, per the root
  README's explicit instruction.

## Directory structure

```
frontend/src/
  app/
    routes/                # one file per route, React Router config
      public/               # landing, projects, contact (no auth)
      admin/                # invoices, budget, inventory admin views
      customer/             # customer invoice view + pay flow
    layout/                 # shell components: shared nav, ascii background, etc.
  components/               # shared, reusable UI components
  api/
    client.ts                # fetch wrapper: attaches CSRF header, handles 401/429
    invoices.ts               # one file per backend feature, typed request/response
    budget.ts
    inventory.ts
    auth.ts
  ascii/
    AsciiCanvas.tsx           # wraps wasm-ascii bindings, see 08
    fallback.ts                # non-WASM CSS/JS rendering path
  hooks/
  styles/
    tokens.css                 # CSS variables, see 09
    tailwind.css
  types/                       # types generated/shared from backend schemas (see below)
```

## Type sharing with the backend

Backend pydantic models are the source of truth. Generate TypeScript
types from the FastAPI OpenAPI schema (`openapi-typescript`) into
`frontend/src/types/api.generated.ts`, committed to the repo and
regenerated via a Makefile target (`make types`, run in CI to catch
drift -- fail the build if generated output differs from committed
output). Never hand-maintain a parallel type definition that can drift
from the backend.

## API client

`api/client.ts` is the only place that talks to `fetch` directly. It:

- Reads the CSRF token from the non-HttpOnly cookie (see
  [02-auth-and-security.md](02-auth-and-security.md)) and attaches it as
  `X-CSRF-Token` on every mutating request.
- On `401`, clears local auth state and redirects to login.
- On `429`, surfaces a typed `RateLimitedError` with the `Retry-After`
  value so calling components can show a real countdown, not a generic
  error.
- Never stores the session token itself in JS-reachable storage
  (`localStorage`/`sessionStorage`) -- the session cookie is HttpOnly by
  design, the frontend should never need to touch it directly.

## Route guards

`app/routes/admin/*` and `app/routes/customer/*` each wrap their route
tree in a guard component that calls a lightweight `GET /api/me`
endpoint via React Query; unauthenticated/wrong-role users are redirected
before any protected component mounts or fetches feature data.

## Build & tooling

```
frontend/Makefile
  install:    npm ci
  build:      npm run build       (tsc --noEmit && vite build)
  test:       see 12-testing-strategy.md
  lint:       eslint .
  fmt:        prettier --write .
  typecheck:  tsc --noEmit
  check:      lint + typecheck + test
  types:      openapi-typescript ../backend/openapi.json -o src/types/api.generated.ts
```

## What NOT to put here

- Visual design system (fonts, colors, motion choices) ->
  [09-design-system.md](09-design-system.md)
- ASCII rendering internals -> [08-ascii-wasm-renderer.md](08-ascii-wasm-renderer.md)
- Test strategy -> [12-testing-strategy.md](12-testing-strategy.md)
