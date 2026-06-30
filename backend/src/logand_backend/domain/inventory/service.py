from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.models.inventory import InventoryItem
from logand_backend.errors import InventoryError


async def create_item(
    db: AsyncSession,
    name: str,
    location_id: UUID,
    quantity: int = 1,
    description: str | None = None,
    tags: list[str] | None = None,
) -> Result[UUID, InventoryError]:
    item_id = uuid4()
    db.add(
        InventoryItem(
            id=item_id,
            name=name,
            location_id=location_id,
            quantity=quantity,
            description=description,
            tags=tags or [],
        )
    )
    await db.flush()
    return Ok(item_id)


async def move_item(
    db: AsyncSession, item_id: UUID, new_location_id: UUID
) -> Result[None, InventoryError]:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return Err(InventoryError.NotFound)
    item.location_id = new_location_id
    await db.flush()
    return Ok(None)


async def update_item_quantity(
    db: AsyncSession, item_id: UUID, quantity: int
) -> Result[None, InventoryError]:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return Err(InventoryError.NotFound)
    item.quantity = quantity
    await db.flush()
    return Ok(None)


async def delete_item(db: AsyncSession, item_id: UUID) -> Result[None, InventoryError]:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return Err(InventoryError.NotFound)
    await db.delete(item)
    await db.flush()
    return Ok(None)


async def search_items(
    db: AsyncSession,
    query: str | None = None,
    location_id: UUID | None = None,
    tag: str | None = None,
) -> Result[list[InventoryItem], InventoryError]:
    """Free-text `query` uses Postgres full-text search
    (to_tsvector('english', name || ' ' || coalesce(description, '')), GIN
    indexed) per docs/design/06 -- not ILIKE, that doesn't scale past a
    couple dozen items and we'd need a migration to switch later anyway.
    See db/migrations/versions/ for the GIN index this relies on.
    """
    stmt = select(InventoryItem)
    if location_id is not None:
        stmt = stmt.where(InventoryItem.location_id == location_id)
    if tag is not None:
        # NOTE: .contains([tag]) (Postgres ARRAY containment) instead of
        # .any(tag) -- the latter resolves to ORM relationship-collection
        # `.any()` in the type stubs (ambiguous with the ARRAY-column `.any`
        # overload), .contains is unambiguous and equivalent for one tag.
        stmt = stmt.where(InventoryItem.tags.contains([tag]))
    if query is not None:
        # search_vector is a generated, GIN-indexed column -- see
        # db/migrations/versions/0001_inventory_fts.py. Querying it directly
        # (rather than recomputing to_tsvector(...) here) is what lets
        # Postgres use the index.
        stmt = stmt.where(
            text("search_vector @@ plainto_tsquery('english', :query)").bindparams(
                query=query
            )
        )

    rows = (await db.execute(stmt)).scalars().all()
    return Ok(list(rows))
