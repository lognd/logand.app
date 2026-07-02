# 14 -- Mileage, Receipts, Documents/CAD

Audience: anyone building the future Android client, or extending any of
these three features. Read [00-overview.md](00-overview.md),
[02-auth-and-security.md](02-auth-and-security.md), and
[13-storage-abstraction.md](13-storage-abstraction.md) first. All three
are admin-only features -- customers never see these.

## Why these three are separate features (not one generic "attachment" table)

Mileage has no file at all. Receipts and documents/CAD both have a file,
but different required-field shapes and different workflows (a receipt
is captured with minimal input and reconciled later; a document is
uploaded already-categorized). Splitting them keeps each route's request
shape obvious and keeps `Receipt`/`Document`'s required-vs-optional
fields accurate, rather than one generic table where "what's actually
required" varies by a `kind` discriminator a client has to know about
out-of-band.

## Mileage (`db/models/mileage.py`, `domain/mileage/`, `api/mileage.py`)

```
mileage_entries
  id               uuid pk
  vehicle          text not null
  occurred_on      date not null
  start_odometer   numeric(10,1)      -- nullable
  end_odometer     numeric(10,1)      -- nullable
  distance         numeric(10,1) not null   -- always populated, see below
  purpose          text               -- nullable
  business         boolean not null default true
  memo             text               -- nullable
  deleted_at / created_at / updated_at
```

**Minimal-input-friendly by design**: a caller supplies EITHER a raw
`distance` (the common "trip was 12.4 miles, done" phone-app case) OR
`start_odometer`+`end_odometer` (the common "photo the dashboard before
and after" case) -- never both required.
`domain/mileage/service.py::_resolve_distance` derives whichever wasn't
supplied; `MileageError.InvalidDistance` (422) if neither form resolves
to a non-negative number. `distance` is always the authoritative,
always-populated column -- every reader should use it, not re-derive from
odometer readings (which may be `None`).

Soft-deleted (`deleted_at`), same convention as invoices/budget --
mileage logs are potentially tax-deduction-relevant records.

Endpoints: `POST /api/admin/mileage`,
`GET /api/admin/mileage?vehicle=&business=&date_from=&date_to=`,
`DELETE /api/admin/mileage/{id}`.

## Receipts (`db/models/receipts.py`, `domain/receipts/`, `api/receipts.py`)

```
receipts
  id                          uuid pk
  file_path / file_hash       text not null   -- the only required fields
  vendor / category / note    text            -- nullable
  amount                      numeric(12,2)   -- nullable
  occurred_on                 date            -- nullable
  reconciled_budget_entry_id  uuid fk -> budget_entries.id, on delete set null
  captured_at / deleted_at / created_at / updated_at
```

**"Record receipts with evidence and minimum user input"** -- the ONLY
required input at capture time is the photo/PDF itself
(`POST /api/admin/receipts`, `multipart/form-data`, allowlisted to
`application/pdf`/`image/png`/`image/jpeg`, same allowlist as budget
evidence). Everything else (vendor, amount, category, which budget entry
this corresponds to) can be filled in later -- a human doing bookkeeping,
or a future OCR/automation step (see "Hooking in automation" below).

Reconciliation is a deliberate, separate step
(`POST /api/admin/receipts/{id}/reconcile?budget_entry_id=`), not
automatic at capture time -- a quick phone capture often happens well
before anyone has decided the right budget category/amount, and forcing
that decision at capture time is exactly the friction this feature exists
to avoid.

`GET /api/admin/receipts/{id}/file` proxies the stored bytes back (or
redirects to a real URL if the storage backend has one -- see
[13-storage-abstraction.md](13-storage-abstraction.md)).

## Documents / CAD (`db/models/documents.py`, `domain/documents/`, `api/documents.py`)

```
documents
  id                  uuid pk
  title                text not null
  category             text not null   -- 'cad'|'manual'|'inventory'|'documentation'|'other'
  tags                 text[]
  file_path / file_hash / content_type   text not null
  inventory_item_id    uuid fk -> inventory_items.id, on delete set null   -- nullable
  deleted_at / created_at / updated_at
```

Generic categorized file storage -- covers "keep track on inventory,
documentation, CAD files" without a new table per document kind; adding a
new category later is a `CHECK` constraint edit
(`db/models/documents.py::DOCUMENT_CATEGORIES`), not a new
table/migration/route set.

Content-type allowlist is deliberately wider than receipts/budget
evidence (`application/zip`, `model/step`, `application/sla` for `.stl`,
etc. in addition to PDF/PNG/JPEG) -- CAD files are legitimately not
images or PDFs.

`inventory_item_id` is optional and `SET NULL` (not `CASCADE`) on the
linked item's delete -- a CAD file or manual often still has value even
after the physical item it described is gone from inventory.

Endpoints: `POST /api/admin/documents`,
`GET /api/admin/documents?category=&tag=&inventory_item_id=`,
`GET /api/admin/documents/{id}/file`, `DELETE /api/admin/documents/{id}`.

## API stability -- this IS the abstraction layer

The explicit ask was "an abstraction layer between multiple endpoints, so
I can hook into this and build an automated tool later." The decision
made here: **one backend, one versioned/stable REST API contract** --
not a plugin system swapping between multiple backend implementations.
Every client (this web frontend today, a future native Android app, a
future automation script) authenticates the same way (session cookie +
CSRF, see [02-auth-and-security.md](02-auth-and-security.md)) and talks
to the same routes documented above. The abstraction a future automated
tool "hooks into" is this API surface itself -- there's no separate
integration layer to build beyond keeping these routes' request/response
shapes stable and additive (new optional fields, not breaking changes to
existing ones) as they evolve.

## Android app

A native Android (Kotlin, Jetpack Compose) app lives at `android/` --
see [`android/README.md`](../../android/README.md) for the full
architecture, build/test instructions, and honest known limitations
(no offline queueing, session doesn't survive process death). It talks
to exactly the API surface documented above: login, mileage
create/list/delete, and receipt capture/list/reconcile/delete, styled
to match the web frontend's Gruvbox Dark palette and JetBrains Mono
typography (see [09-design-system.md](09-design-system.md)).

Structured as two modules: `:core` (plain Kotlin/JVM -- the API client,
models, CSRF handling -- no Android dependency, builds and tests with a
bare JDK) and `:app` (the real Android application, Compose UI,
ViewModels). `:core` is genuinely the "abstraction layer" the original
ask was for -- every screen in `:app`, and any future automated tool,
talks to the backend only through `ApiClient`, never a raw HTTP call
of its own.

## Testing

Each feature's `is_err`/404/422 branches, filter combinations, and (for
receipts/documents) file round-trip-through-storage are covered in
`tests/system/test_mileage_api.py`, `test_receipts_api.py`, and
`test_documents_api.py` respectively -- see
[12-testing-strategy.md](12-testing-strategy.md).
