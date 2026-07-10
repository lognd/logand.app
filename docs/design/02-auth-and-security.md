# 02 -- Auth & Security

Audience: anyone building login, sessions, rate limiting, password
storage, or CSRF protection. Read [00-overview.md](00-overview.md) first.

This doc is the single source of truth for security mechanics. Every
other feature doc (invoices, budget, inventory) references this one for
"how is this endpoint protected" instead of re-deciding it.

## Threat model summary

Two user classes:

- **Admin** (Logan only, exactly one account): full access to every
  endpoint, including budget/inventory which customers never see.
  "Absolute power" means no feature flag or permission check ever blocks
  the admin account -- but the admin account itself must still be hard
  to compromise (strong password + hashing + rate-limited login + session
  revocation).
- **Customer**: scoped access, can only view/pay their own invoices.
  Never sees budget or inventory data, never sees other customers' data.

Public, unauthenticated surface: landing page, projects page, contact
info, SEO/agent-accessible content (see
[10-seo-and-agent-accessibility.md](10-seo-and-agent-accessibility.md)),
and the invoice-payment entry point (which then requires customer auth
or a scoped invoice token, see [04-invoices.md](04-invoices.md)).

## Sessions

- Server-side sessions stored in PostgreSQL (`sessions` table, see
  [03-database.md](03-database.md)).
- Session ID: 256-bit random token (`secrets.token_urlsafe(32)`), stored
  **hashed** (SHA-256) in the DB -- the raw token only ever exists in the
  cookie and in-memory during the request that issues it. This means a DB
  leak alone does not let an attacker replay sessions.
- Cookie attributes: `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`.
  Name: `__Host-session` (the `__Host-` prefix enforces Secure+no-Domain
  at the browser level).
- Session expiry: sliding window, 30 minutes idle timeout for customer
  sessions, 12 hours idle timeout for admin (admin logs in less often,
  sessions should survive a workday). Absolute max lifetime 7 days
  either way, then forced re-auth.
- Revocation: deleting the DB row invalidates the session immediately on
  the next request. Admin gets a "kill all sessions" endpoint (kills
  every session in the table, including their own -- the nuclear option).

## Password storage

- Argon2id via `argon2-cffi`. Never bcrypt/PBKDF2/raw SHA for passwords.
- Parameters: time_cost=3, memory_cost=64MB, parallelism=4 (OWASP
  current baseline; revisit if VPS RAM is constrained -- see
  [11-deployment.md](11-deployment.md) for VPS sizing).
- No password length cap below 128 chars. No composition rules
  (no forced special-characters) -- length + Argon2id is the defense.

## CSRF

- Double-submit token: a `csrf_token` is set as a non-HttpOnly cookie on
  session creation, and the frontend must echo it back in an
  `X-CSRF-Token` header on every state-changing request (POST/PUT/PATCH/
  DELETE). Backend middleware rejects state-changing requests where the
  header doesn't match the cookie.
- GET requests are never state-changing and never need the token.
- This is in addition to `SameSite=Strict`, not instead of it -- defense
  in depth, since `SameSite` alone has had browser-specific bypass
  history.

## Rate limiting

- Token-bucket limiter, backed by Redis (add `redis` service to
  [11-deployment.md](11-deployment.md)'s docker-compose) or, if Redis is
  deferred for v1, an in-process limiter with the explicit understanding
  it resets on restart and doesn't share state across workers -- flag
  this as a known v1 limitation, not a silent gap.
- Thresholds (per IP, unless noted):
  - Login attempts: 5 / 15 min, then exponential backoff lockout on that
    IP+username pair.
  - Customer invoice-payment endpoints: 20 / min.
  - General authenticated API: 120 / min.
  - Admin API: 300 / min (generous, but not infinite -- see threat model).
  - Public/unauthenticated read endpoints (landing page data, SEO
    endpoints): 60 / min, deliberately loose so legitimate crawlers
    aren't blocked (cross-reference
    [10-seo-and-agent-accessibility.md](10-seo-and-agent-accessibility.md)).
- Exceeding a limit returns `429` with `Retry-After`, never silently
  drops the request.

## Secrets handling

- `.env` is never read by an agent, directly or indirectly, at any
  point -- this is a hard rule from the root user instructions, not just
  this project. If a task seems to require reading `.env`, stop and ask
  the human to paste the specific value needed, or better, restructure
  the task so it doesn't require it.
- Required secrets (document names only, never values, in
  `backend/.env.example` with placeholders):
  - `SESSION_SECRET` -- HMAC key for signing CSRF tokens, not session
    IDs themselves (session IDs are random, not signed/derived).
  - `DATABASE_URL`
  - `PAYMENT_PROCESSOR_SECRET` (see [04-invoices.md](04-invoices.md))
- GitHub Actions secrets: same rule, never read or print `.github`
  workflow secret values, even indirectly via `echo $SECRET` in a
  workflow you're authoring -- write workflows that pass secrets as env
  vars to tooling, never to shell echo/log statements.

## Authorization model

- Two roles only at v1: `admin`, `customer`. No need for a generic RBAC
  system given one admin account ever exists -- don't over-engineer this.
- Every router function declares its required role via a FastAPI
  dependency (`Depends(require_admin)` / `Depends(require_customer)`),
  checked centrally in `auth/sessions.py`. No endpoint should do ad-hoc
  role checks inline.
- Customer-scoped data access (a customer can only see *their own*
  invoices) is enforced at the query layer in `domain/invoices/`, not
  just at the router layer -- always filter by `customer_id` derived
  from the session, never trust a customer-supplied ID without checking
  ownership.

## Account states and email verification

As of `docs/design/17-contact-users-and-email-verification.md`, a `users`
row is no longer necessarily an account. It is one of three states:

- **contact** (`password_hash IS NULL`) -- an address an admin has invoiced.
  Nothing can authenticate as it.
- **unverified** (password set, `email_verified_at IS NULL`) -- someone
  claimed the address but has not proven they control the inbox.
- **active** -- inbox control proven.

Self-registration is open and unauthenticated, so a registrant asserting an
email address proves nothing. The consequence for authorization:

> Customer-scoped invoice access is gated on `email_verified_at IS NOT NULL`,
> never on the mere fact that an invoice's `customer_id` points at the row.

`auth/sessions.py::validate_session` refuses to issue a valid session for a
contact or unverified row, so the gate sits below every router-level role
check rather than beside it. Registering over an unverified row is permitted
(it re-mints verification); registering over an active row is refused.
Whoever controls the inbox wins -- that is the only correct tiebreak, and it
is what stops an attacker from either stealing or squatting an address.

## Testing this doc's mechanics

Auth-specific test cases (session expiry, CSRF rejection, rate-limit
429s, Argon2id round-trip, cross-customer data isolation) are
unit/integration test obligations -- see
[12-testing-strategy.md](12-testing-strategy.md) for the general
strategy and where these specific cases live.
