---
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
---

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

