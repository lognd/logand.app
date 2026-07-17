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
