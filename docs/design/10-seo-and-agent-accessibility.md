# 10 -- SEO & AI-Agent Accessibility

Audience: anyone building the public landing/projects/contact pages or
the metadata/structured-data layer. Read [00-overview.md](00-overview.md)
first. This applies only to the **public, unauthenticated** surface --
never expose invoice/budget/inventory data to crawlers (see
[02-auth-and-security.md](02-auth-and-security.md) for what's behind
auth).

## Two audiences, one content source

Root README asks for the site to be both stylistically beautiful for
humans and highly visible/parseable for crawlers and AI agents (search
engines, ChatGPT, Claude, etc). The approach: render real, semantic HTML
server-side (or statically) for every public page -- not a JS-only SPA
shell -- so both humans and agents get the same content; the ASCII/WASM
visual layer (see [08](08-ascii-wasm-renderer.md)) is decoration on top
of real markup, never a replacement for it.

## Rendering strategy

Public routes (`frontend/src/app/routes/public/`, see
[07-frontend-architecture.md](07-frontend-architecture.md)) use
pre-rendering/SSG (Vite's SSG plugin, or a prerender step in CI that
snapshots the public routes to static HTML at build time) rather than
relying on client-side React rendering for content a crawler needs.
Admin/customer routes stay client-rendered SPA -- they're behind auth,
crawlers never see them, no SEO concern there.

## Structured data

Every public page ships JSON-LD (`<script type="application/ld+json">`):

- Landing page: `Person` schema (Logan Dapp) with `sameAs` links to
  professional profiles the human fills in, `jobTitle`, `url`.
- Projects page: `CreativeWork`/`SoftwareSourceCode` entries per
  project.
- Contact: `ContactPoint` embedded in the `Person` schema, not a
  separate page-level schema.

This directly serves AI agents doing retrieval (structured data is far
more reliable for an LLM-driven crawler to parse correctly than prose)
as well as classic SEO rich-result eligibility.

## Semantic HTML & metadata baseline

- One `<h1>` per page, real heading hierarchy (no skipped levels)
- `<meta name="description">` per route, human-written not generic
- Open Graph + Twitter Card tags per route (image, title, description)
- `<link rel="canonical">` on every public route
- `robots.txt` explicitly allows all major crawlers including AI-agent
  user agents (`GPTBot`, `ClaudeBot`, `PerplexityBot`, etc.) on public
  routes, and explicitly disallows `/api/admin/`, `/api/invoices`,
  `/admin/`, `/customer/` -- belt-and-suspenders on top of auth, not a
  substitute for it.
- `sitemap.xml` generated at build time from the known public route
  list.

## llms.txt

Ship an `llms.txt` at the site root (emerging convention for
AI-agent-readable site summaries) -- a concise markdown summary of who
Logan is, what the site contains, and links to the most important
public pages. Low cost, directly serves the root README's "optimize for
visibility to AI web agents" goal, and is a natural complement to
JSON-LD rather than a replacement for it.

## Performance

Crawlers and agents (and the "elderly first-time user" bar in
[09-design-system.md](09-design-system.md)) both benefit from fast
loads: prerendered HTML ships immediately, the WASM ASCII layer loads
async and never blocks first paint of real content
(`<link rel="modulepreload">` for the WASM bundle, but content renders
before it resolves).

## Testing

Structured-data validity (JSON-LD schema conformance) and
prerendered-HTML-contains-real-content checks belong in the frontend
system-test layer -- see
[12-testing-strategy.md](12-testing-strategy.md).
