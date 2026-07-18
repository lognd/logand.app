# Tickets

Central ledger managed by `frob ticket` -- one section per ticket.

<!-- ticket:T-0001 -->
```yaml
id: T-0001
title: Close COV001 doc-coverage gap on legacy surface
state: queued
kind: docs
origin: human
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- backend/src/**
- frontend/src/**
evidence: []
attachments: []
acceptance: []
threat: null
```
## Context

Frob adoption baseline (frob.toml, T-0000-equivalent chore commit) set
COV001 to warn severity for the pre-existing legacy surface. `frob check
--only gates` reports 892 COV001 warnings repo-wide: public symbols with
no `frob:doc` edge to a doc anchor, across backend/src and frontend/src.

## Plan

Work through packages incrementally, adding `frob:doc` anchors (doc
comments plus `<!-- frob:describes path::symbol -->` in the owning
docs/design/*.md file) for the highest-traffic modules first
(backend/src/logand_backend/domain/invoices, frontend/src/api). Flip
COV001 back to error in frob.toml once the legacy surface is clear, per
the note left in [gates.severity].

## Done report

(fill in on close)

<!-- ticket:T-0002 -->
```yaml
id: T-0002
title: Add missing frob:tests unit edges (TEST001) for public symbols
state: queued
kind: feature
origin: human
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- backend/src/**
- frontend/src/**
- wasm-ascii/src/**
evidence: []
attachments: []
acceptance: []
threat: null
```
## Context

`frob check --only gates` reports 664 TEST001 warnings: public
functions/methods with no `frob:tests` unit edge, across the legacy
backend/frontend/wasm-ascii surface (TEST001 set to warn in frob.toml's
legacy-adoption baseline).

## Plan

Bind existing tests to their target symbols via `# frob:tests
path::symbol` (Python/TS) or `// frob:tests path::symbol` (Rust)
directives above each `it`/`test`/`def test_*` that already exercises a
public symbol -- most of the 664 likely already have a covering test that
is simply unbound, not missing. True gaps get a new unit test. Flip
TEST001 back to error in frob.toml once clear.

## Done report

(fill in on close)

<!-- ticket:T-0003 -->
```yaml
id: T-0003
title: Add integration frob:tests edges for TEST003 interfaces (26 packages)
state: queued
kind: feature
origin: human
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- backend/src/**
- frontend/src/**
- ops/**
- scripts/**
- wasm-ascii/src/**
evidence: []
attachments: []
acceptance: []
threat: null
```
## Context

`frob check --only gates` reports 26 TEST003 warnings: packages/directory
"interfaces" (alpha semantics: any directory with a public, non-test
symbol) below `min_integration=1` bound integration `frob:tests` edges.
Includes backend/src/logand_backend, most frontend/src/* subpackages,
ops/release_watch/src, scripts, scripts/prodtest/*, and wasm-ascii/src/*.

## Plan

For each flagged interface, add one `frob:tests <path> kind="integration"`
edge on an existing integration/system test that already exercises that
package's public surface end to end (backend/tests/integration/*.py and
frontend/tests/system/* are the natural homes). Several frontend
subpackages (styles, mocks) may be false positives under alpha's
directory-based derivation -- note those explicitly rather than forcing a
test that doesn't fit, and consider excluding them from [graph] if they
truly own no real public interface.

## Done report

(fill in on close)

<!-- ticket:T-0004 -->
```yaml
id: T-0004
title: Audit tenant/owner-scoping on backend/scheduler SQL queries (CWE-639)
state: queued
kind: security
origin: human
created: '2026-07-18'
blocked_by: []
parent: null
scope:
- backend/src/logand_backend/domain/**
- backend/src/logand_backend/db/**
evidence: []
attachments: []
acceptance: []
threat: elevation-of-privilege
```
strata pilot (design/logand-app.strata) declared backend/scheduler's real may "sql" capability, which drags in a CWE-639 (misused dynamic ORM condition / authz-scoping bypass) obligation under the web-performance-baseline/reliability-baseline/web-quality-security-baseline audit views. This pass verified query PARAMETERIZATION only (no raw string-built SQL under backend/src/logand_backend/db/** or domain/**, confirmed by grep for f-string/.format/% interpolation feeding execute/text calls -- none found). It did NOT verify that every customer-facing query correctly scopes rows to the authenticated user/tenant (the actual CWE-639 concern: could one authenticated user's request read/modify another's rows via an unscoped or attacker-influenced filter). Left deliberately undischarged in the strata model rather than assumed away without evidence -- see design/logand-app.strata's own comment at the CWE-639 claim site. Close by walking every query under domain/** that filters by an id derived from request input and confirming it also filters by the authenticated principal, then add either a real fix or a properly-evidenced assume in the strata file.

<!-- ticket:T-0005 -->
```yaml
id: T-0005
title: 'Close strata wiring follow-ups: android client_storage scan, frob:tests edges
  for design flows'
state: queued
kind: docs
origin: human
created: '2026-07-18'
blocked_by: []
parent: null
scope:
- design/logand-app.strata
evidence: []
attachments: []
acceptance: []
threat: null
```
Tracks two deferred items from the strata pilot wiring (design/logand-app.strata, docs/design/18-strata-system-model.md): (1) android's local storage (DataStore/SharedPreferences) was not verified against the client_storage capability -- Kotlin capability scanning was out of scope for the pilot's time budget, see the frob:todo T-0005 anchor on the android node. (2) every flow/boundary symbol in design/logand-app.strata reports TEST001 (no frob:tests unit edge) -- design constructs are not code and have no direct unit test the way a function does; decide whether frob:tests should accept a convention-based match against a system/integration test exercising that flow (e.g. f_backend_stripe -> backend/tests/system/test_stripe_webhooks.py) or whether TEST001 should stay warn-severity for design/**.strata files the way legacy code TEST001 warnings are handled in frob.toml today. Close by either wiring frob:tests edges to the real system tests that already exercise each flow, or by documenting the intentional gap.
