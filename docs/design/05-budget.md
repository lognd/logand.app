# 05 -- Budget / Expense Ledger

Audience: anyone building the expense-tracking feature. Read
[00-overview.md](00-overview.md) and [02-auth-and-security.md](02-auth-and-security.md)
first. Admin-only feature -- customers never see this.

## Purpose

Audit-grade record of business expenses: what was spent, why, and proof
it happened. The bar is "bulletproof if I get audited" per the root
README -- that drives the schema below toward immutability and evidence
attachment over editability.

## Schema

```
budget_entries
  id              uuid pk
  amount          numeric(12,2) not null
  category        text not null          -- e.g. 'supplies', 'travel', 'software'
  vendor          text
  memo            text
  occurred_on     date not null            -- date of the expense, not entry creation
  deleted_at      timestamptz null         -- soft delete, see 03 -- never hard-delete
  created_at / updated_at

budget_entry_evidence
  id               uuid pk
  budget_entry_id  uuid fk -> budget_entries.id, on delete cascade
  file_path        text not null            -- path within object storage, see below
  file_hash        text not null            -- sha256 of the file, for integrity verification
  uploaded_at       timestamptz
```

## Immutability rule

Once a `budget_entries` row has at least one evidence file attached, its
`amount`, `category`, `occurred_on`, and `vendor` fields become
**append-only edit via correction, not overwrite**: an edit creates a
new row referencing the old one via `corrects_entry_id uuid null fk`,
and the old row is marked `deleted_at` (soft-deleted, never erased). An
auditor needs to see the original entry and the correction, not a
silently overwritten value. Implement this as a domain-layer rule
(`domain/budget/corrections.py`), not a DB trigger -- keep it
testable and explicit in Python.

## Evidence storage

Receipt images/PDFs go to filesystem storage on the VPS (a dedicated
Docker volume, see [11-deployment.md](11-deployment.md)), not the
database -- BYTEA columns for files bloat backups and slow queries.
`file_hash` lets the admin verify a file hasn't been tampered with
independent of the filesystem's own guarantees.

v1 explicitly does not need S3/cloud object storage -- single-VPS
deployment with regular backups (see
[11-deployment.md](11-deployment.md)) is sufficient for personal-business
scale. Revisit only if storage volume becomes a real constraint.

## Endpoints (`api/budget.py`, `require_admin` on all)

- `POST /api/admin/budget` -- create entry
- `POST /api/admin/budget/{id}/evidence` -- upload evidence (multipart),
  computes and stores `file_hash` server-side, rejects non-PDF/image
  content types
- `PATCH /api/admin/budget/{id}` -- if no evidence attached yet, direct
  edit is fine; if evidence exists, this creates a correction row (see
  above) instead of mutating in place
- `GET /api/admin/budget` -- list/filter (category, date range)
- `GET /api/admin/budget/export` -- CSV export for tax prep / accountant
  handoff; this is the actual "bulletproof for an audit" deliverable,
  don't treat it as an afterthought

## Testing

The correction-not-overwrite invariant (editing an entry with evidence
never destroys the original row) is the highest-value test here -- see
[12-testing-strategy.md](12-testing-strategy.md).
