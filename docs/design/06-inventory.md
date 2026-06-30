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
  location_id     uuid fk -> inventory_locations.id, on delete restrict
  tags            text[]                 -- e.g. {'resistor','smd','0603'}
  created_at / updated_at
```

No soft-delete here (see [03-database.md](03-database.md) rule) --
inventory isn't an audit artifact, hard delete is correct when an item
is gone.

`location_id` is `restrict` on delete: you can't delete a location while
items still reference it, forcing an explicit move-or-delete-items step
rather than silently orphaning data.

## Endpoints (`api/inventory.py`, `require_admin` on all)

- `POST /api/admin/inventory/locations`
- `GET /api/admin/inventory/locations`
- `POST /api/admin/inventory/items`
- `PATCH /api/admin/inventory/items/{id}` -- includes quantity adjust
  and location move
- `GET /api/admin/inventory/items?location_id=&tag=&q=` -- filter by
  location, tag, or free-text search over `name`/`description`
- `DELETE /api/admin/inventory/items/{id}`

## Search

`q` free-text search uses Postgres full-text search
(`to_tsvector('english', name || ' ' || coalesce(description, ''))`,
GIN-indexed) rather than `ILIKE '%...%'` -- cheap to add now, much
better UX once the inventory grows past a few dozen items, and avoids a
later migration.

## Testing

Location-delete-restrict behavior and tag/text search correctness are
the cases worth covering -- see
[12-testing-strategy.md](12-testing-strategy.md).
