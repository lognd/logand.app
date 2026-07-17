---
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
---

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

