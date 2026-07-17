---
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
---

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

