# 06 -- Personal Inventory

Audience: anyone building the inventory tracking feature. Read
[00-overview.md](00-overview.md) and [02-auth-and-security.md](02-auth-and-security.md)
first. Admin-only feature -- customers never see this.

## Purpose

Track personal inventory (electronic components, tools, etc.) and where
each item physically lives. Root README explicitly scopes v1 to "start
with protected API" -- no fancy UI requirement yet, just a solid,
super-user-friendly backend surface the admin can hit (a simple admin UI
is in scope for the frontend per [07](07-frontend-architecture.md), but
barcode scanning, label printing, etc. are explicitly out of scope for
v1 unless requested later).

## Schema

```
inventory_locations
  id            uuid pk
  name          text unique not null    -- e.g. "garage shelf 3", "desk drawer A"
  description   text
  created_at / updated_at

inventory_items
  id              uuid pk
  name            text not null
  description     text
  quantity        integer not null default 1
  unit_cost       numeric(12,4)          -- nullable; required before a BOM
                                          -- can compute a cost breakdown
                                          -- that includes this item
  location_id     uuid fk -> inventory_locations.id, on delete restrict
  tags            text[]                 -- e.g. {'resistor','smd','0603'}
  created_at / updated_at

inventory_adjustments               -- append-only audit trail, never updated/deleted
  id              uuid pk
  item_id         uuid fk -> inventory_items.id
  delta           integer not null       -- signed; quantity_after = quantity_before + delta
  quantity_before integer not null
  quantity_after  integer not null       -- CHECK (quantity_after = quantity_before + delta)
  reason          text not null
  adjusted_by     uuid fk -> users.id, nullable (on delete set null)
  created_at
```

No soft-delete on `inventory_items`/`inventory_locations` (see
[03-database.md](03-database.md) rule) -- inventory isn't an audit
artifact, hard delete is correct when an item is gone.
`inventory_adjustments` IS append-only by design: it's the audit trail
that makes manual quantity changes reconstructable after the fact (see
"Manual adjustments" below), not something ever edited or pruned.

`location_id` is `restrict` on delete: you can't delete a location while
items still reference it, forcing an explicit move-or-delete-items step
rather than silently orphaning data.

## Endpoints (`api/inventory.py`, `require_admin` on all)

- `POST /api/admin/inventory/locations`
- `GET /api/admin/inventory/locations`
- `POST /api/admin/inventory/items`
- `PATCH /api/admin/inventory/items/{id}` -- name/description/location/tags
- `PATCH /api/admin/inventory/items/{id}/unit-cost` -- deliberately
  separate from the general PATCH above (see "Manual adjustments" for
  why quantity has its own route too)
- `POST /api/admin/inventory/items/{id}/adjust` -- the ONLY way to
  change `quantity` (see below); body is `{delta, reason}`
- `GET /api/admin/inventory/items/{id}/adjustments` -- that item's full
  adjustment history, newest first
- `GET /api/admin/inventory/items?location_id=&tag=&q=` -- filter by
  location, tag, or free-text search over `name`/`description`
- `DELETE /api/admin/inventory/items/{id}`

## Manual adjustments (`domain/inventory/service.py::adjust_item_quantity`)

Quantity is never set directly (there is no `quantity` field on the
general item-update PATCH) -- every change goes through `/adjust`,
which locks the row (`SELECT ... FOR UPDATE`), rejects a delta that
would take quantity negative
(`InventoryError.WouldGoNegative`), and writes an
`inventory_adjustments` row alongside the update in the same
transaction. This is what makes "how did this item's count get to
where it is" a real, reconstructable question instead of a mystery, and
is the same row-locked pattern BOM's `consume_bom` (below) reuses for
each of its own per-line adjustments -- a second `FOR UPDATE` on an
already-locked row within the same transaction is a safe re-lock, not a
second real lock.

The admin UI requires an explicit confirm step showing the exact
before-to-after quantity change before the request fires -- see
[15-admin-tools-and-observability.md](15-admin-tools-and-observability.md)
for this site-wide confirmation convention.

## Bill of materials (`domain/bom/`, `api/bom.py`)

```
bill_of_materials
  id                 uuid pk
  name               text not null
  description        text
  labor_hours        numeric(10,2) not null default 0
  labor_rate         numeric(12,4) not null default 0    -- $/hour
  overhead_percent   numeric(5,2) not null default 0      -- applied to material+labor
  created_at / updated_at

bom_material_lines
  bom_id             uuid fk -> bill_of_materials.id
  item_id            uuid fk -> inventory_items.id
  quantity_per_unit  numeric(12,4) not null
  unique(bom_id, item_id)
```

A BOM ties a set of inventory items (with per-unit quantities) plus a
labor/overhead rate to a real, computable cost breakdown:

```
material_cost = sum(item.unit_cost * line.quantity_per_unit * build_quantity)
labor_cost    = labor_hours * build_quantity * labor_rate
overhead_cost = (material_cost + labor_cost) * (overhead_percent / 100)
total_cost    = material_cost + labor_cost + overhead_cost
```

Computing a breakdown fails loudly (`BomError.MissingUnitCost`) if any
line's item has no `unit_cost` set, rather than silently treating it as
zero -- a cost breakdown that quietly drops a real cost is worse than
one that refuses to compute until the gap is filled in.

`POST /api/admin/boms/{id}/consume` ("record a build") is a two-phase
check-then-write: every line's stock sufficiency is verified (row-locked
via `FOR UPDATE`) BEFORE any line is written, so a build that's short on
even one component leaves every line -- including the ones with
plenty of stock -- completely untouched, not partially consumed.
Each line's actual write reuses `adjust_item_quantity` above, so a BOM
consumption shows up in the exact same `inventory_adjustments` audit
trail as a manual adjustment, with `reason` set to identify it as a
BOM build.

The admin invoice-creation UI can import a BOM's cost breakdown
directly as invoice line items (material, a labor line, an overhead
line) -- see [04-invoices.md](04-invoices.md).

## Search

`q` free-text search uses Postgres full-text search
(`to_tsvector('english', name || ' ' || coalesce(description, ''))`,
GIN-indexed) rather than `ILIKE '%...%'` -- cheap to add now, much
better UX once the inventory grows past a few dozen items, and avoids a
later migration.

## Testing

Location-delete-restrict behavior and tag/text search correctness are
the cases worth covering for the base inventory feature. For manual
adjustments: the negative-quantity rejection, the audit trail's
before/after correctness, and (for BOM) `consume_bom`'s all-or-nothing
atomicity when one line lacks sufficient stock -- see
[12-testing-strategy.md](12-testing-strategy.md).
