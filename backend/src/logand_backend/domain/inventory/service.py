from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.models.inventory import InventoryAdjustment, InventoryItem
from logand_backend.errors import InventoryError


async def create_item(
    db: AsyncSession,
    name: str,
    location_id: UUID,
    quantity: int = 1,
    description: str | None = None,
    tags: list[str] | None = None,
    unit_cost: Decimal | None = None,
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
            unit_cost=unit_cost,
        )
    )
    await db.flush()
    return Ok(item_id)


async def set_item_unit_cost(
    db: AsyncSession, item_id: UUID, unit_cost: Decimal
) -> Result[None, InventoryError]:
    """The only way to actually populate InventoryItem.unit_cost -- a real
    gap this closes: without it, a BOM's material-cost computation
    (domain/bom/service.py::compute_cost_breakdown) had no way to ever
    succeed against a real item, only against manually-seeded test data.
    """
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return Err(InventoryError.NotFound)
    item.unit_cost = unit_cost
    await db.flush()
    return Ok(None)


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


async def adjust_item_quantity(
    db: AsyncSession,
    item_id: UUID,
    delta: int,
    reason: str,
    adjusted_by: UUID | None,
) -> Result[UUID, InventoryError]:
    """The real manual-adjustment path -- a signed delta (+5 restocked,
    -3 sold/used) with a required reason, not update_item_quantity's
    absolute set-to-value. Every call writes one permanent
    InventoryAdjustment row alongside the quantity change, in the SAME
    transaction, so the audit trail and the actual quantity can never
    drift apart (a crash between the two would roll both back together).

    `SELECT ... FOR UPDATE` locks the item row for the duration of this
    transaction -- without it, two concurrent adjustments (two admins,
    or an admin racing a BOM-driven consumption) could both read the
    same starting quantity and each compute their own "before" value,
    silently losing one of the two adjustments. Same real concurrency
    concern as domain/invoices/service.py's lock_invoice_for_update.
    """
    item = (
        await db.execute(
            select(InventoryItem).where(InventoryItem.id == item_id).with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        return Err(InventoryError.NotFound)

    quantity_before = item.quantity
    quantity_after = quantity_before + delta
    if quantity_after < 0:
        return Err(InventoryError.WouldGoNegative)

    item.quantity = quantity_after
    adjustment_id = uuid4()
    db.add(
        InventoryAdjustment(
            id=adjustment_id,
            item_id=item_id,
            delta=delta,
            quantity_before=quantity_before,
            quantity_after=quantity_after,
            reason=reason,
            adjusted_by=adjusted_by,
        )
    )
    await db.flush()
    return Ok(adjustment_id)


async def list_item_adjustments(
    db: AsyncSession, item_id: UUID
) -> Result[list[InventoryAdjustment], InventoryError]:
    """The rollback/history view -- "see exactly what changed from what
    to what," newest first."""
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return Err(InventoryError.NotFound)
    rows = (
        (
            await db.execute(
                select(InventoryAdjustment)
                .where(InventoryAdjustment.item_id == item_id)
                .order_by(InventoryAdjustment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return Ok(list(rows))


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
