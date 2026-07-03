from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.models.bom import BillOfMaterials, BomMaterialLine
from logand_backend.db.models.inventory import InventoryItem
from logand_backend.domain.inventory.service import adjust_item_quantity
from logand_backend.errors import BomError


async def create_bom(
    db: AsyncSession,
    name: str,
    labor_hours: Decimal = Decimal(0),
    labor_rate: Decimal = Decimal(0),
    overhead_percent: Decimal = Decimal(0),
    description: str | None = None,
) -> Result[UUID, BomError]:
    bom_id = uuid4()
    db.add(
        BillOfMaterials(
            id=bom_id,
            name=name,
            description=description,
            labor_hours=labor_hours,
            labor_rate=labor_rate,
            overhead_percent=overhead_percent,
        )
    )
    await db.flush()
    return Ok(bom_id)


async def get_bom(db: AsyncSession, bom_id: UUID) -> Result[BillOfMaterials, BomError]:
    bom = await db.get(BillOfMaterials, bom_id)
    if bom is None:
        return Err(BomError.NotFound)
    return Ok(bom)


async def list_boms(db: AsyncSession) -> Result[list[BillOfMaterials], BomError]:
    rows = (
        (await db.execute(select(BillOfMaterials).order_by(BillOfMaterials.name)))
        .scalars()
        .all()
    )
    return Ok(list(rows))


async def delete_bom(db: AsyncSession, bom_id: UUID) -> Result[None, BomError]:
    bom = await db.get(BillOfMaterials, bom_id)
    if bom is None:
        return Err(BomError.NotFound)
    await db.delete(bom)
    await db.flush()
    return Ok(None)


async def add_material_line(
    db: AsyncSession, bom_id: UUID, item_id: UUID, quantity_per_unit: int
) -> Result[UUID, BomError]:
    bom = await db.get(BillOfMaterials, bom_id)
    if bom is None:
        return Err(BomError.NotFound)
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return Err(BomError.ItemNotFound)

    # Checked proactively, not caught via IntegrityError -- a caught
    # constraint violation would need a db.rollback() to bring the
    # transaction back to a usable state (Postgres aborts the whole
    # transaction on a failed statement), but that rollback would also
    # discard everything ELSE this same session/transaction had already
    # done (a caller building up several changes in one request, or a
    # test session spanning multiple calls). A plain existence check
    # avoids that entirely; uq_bom_material_lines_bom_item stays in place
    # purely as a real DB-level safety net against a genuine race, not
    # the primary detection path.
    existing = (
        await db.execute(
            select(BomMaterialLine).where(
                BomMaterialLine.bom_id == bom_id, BomMaterialLine.item_id == item_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return Err(BomError.DuplicateItem)

    line_id = uuid4()
    db.add(
        BomMaterialLine(
            id=line_id,
            bom_id=bom_id,
            item_id=item_id,
            quantity_per_unit=quantity_per_unit,
        )
    )
    await db.flush()
    return Ok(line_id)


async def remove_material_line(
    db: AsyncSession, bom_id: UUID, item_id: UUID
) -> Result[None, BomError]:
    line = (
        await db.execute(
            select(BomMaterialLine).where(
                BomMaterialLine.bom_id == bom_id, BomMaterialLine.item_id == item_id
            )
        )
    ).scalar_one_or_none()
    if line is None:
        return Err(BomError.MaterialLineNotFound)
    await db.delete(line)
    await db.flush()
    return Ok(None)


class BomMaterialLineCost(BaseModel):
    model_config = {"frozen": True}

    item_id: UUID
    item_name: str
    quantity: int
    unit_cost: Decimal
    line_cost: Decimal


class BomCostBreakdown(BaseModel):
    """The real material/time/overhead breakdown -- "it would be nice to
    give a price breakdown of material and time and overhead," directly.
    Every figure here is already scaled by `build_quantity` (a BOM
    describes the cost of ONE unit; a real build/invoice is usually for
    more than one).
    """

    model_config = {"frozen": True}

    material_lines: list[BomMaterialLineCost]
    material_cost: Decimal
    labor_hours: Decimal
    labor_cost: Decimal
    overhead_percent: Decimal
    overhead_cost: Decimal
    total_cost: Decimal


async def compute_cost_breakdown(
    db: AsyncSession, bom_id: UUID, build_quantity: int = 1
) -> Result[BomCostBreakdown, BomError]:
    bom = await db.get(BillOfMaterials, bom_id)
    if bom is None:
        return Err(BomError.NotFound)

    lines = (
        await db.execute(
            select(BomMaterialLine, InventoryItem)
            .join(InventoryItem, BomMaterialLine.item_id == InventoryItem.id)
            .where(BomMaterialLine.bom_id == bom_id)
        )
    ).all()

    line_costs: list[BomMaterialLineCost] = []
    material_cost = Decimal(0)
    for material_line, item in lines:
        if item.unit_cost is None:
            # Surfaced immediately, not silently treated as free -- see
            # InventoryItem.unit_cost's own doc comment.
            return Err(BomError.MissingUnitCost)
        quantity = material_line.quantity_per_unit * build_quantity
        line_cost = item.unit_cost * quantity
        material_cost += line_cost
        line_costs.append(
            BomMaterialLineCost(
                item_id=item.id,
                item_name=item.name,
                quantity=quantity,
                unit_cost=item.unit_cost,
                line_cost=line_cost,
            )
        )

    labor_hours = bom.labor_hours * build_quantity
    labor_cost = labor_hours * bom.labor_rate
    overhead_cost = (material_cost + labor_cost) * (bom.overhead_percent / Decimal(100))
    total_cost = material_cost + labor_cost + overhead_cost

    return Ok(
        BomCostBreakdown(
            material_lines=line_costs,
            material_cost=material_cost,
            labor_hours=labor_hours,
            labor_cost=labor_cost,
            overhead_percent=bom.overhead_percent,
            overhead_cost=overhead_cost,
            total_cost=total_cost,
        )
    )


async def consume_bom(
    db: AsyncSession,
    bom_id: UUID,
    build_quantity: int,
    adjusted_by: UUID | None,
    reason: str | None = None,
) -> Result[list[UUID], BomError]:
    """A programmatic way to update inventory from a bill of materials --
    deducts every material line's (quantity_per_unit *
    build_quantity) from real stock, writing one audited
    InventoryAdjustment per item (via domain/inventory/service.py's
    adjust_item_quantity, so this shares the exact same rollback-record
    guarantee manual adjustments get).

    Two-phase, not "adjust as we go": every line is checked against
    current stock FIRST (all locked via SELECT ... FOR UPDATE), and only
    if EVERY line has enough stock does this proceed to actually write
    any adjustments. Checking-then-writing line-by-line instead would
    let a build partially consume some items before discovering the 4th
    of 5 doesn't have enough stock -- an all-or-nothing failure here
    means a rejected consume() genuinely changed nothing, not "changed
    everything except the one line that failed."
    """
    if build_quantity <= 0:
        # A zero/negative build_quantity would make `need` <= 0 below, so
        # `item.quantity < need` is always false (the stock check always
        # "passes") and the later `-need` adjustment becomes a positive
        # delta -- i.e. a "consumption" that actually ADDS stock. Reject
        # outright rather than relying on every caller to already enforce
        # this at the API layer.
        return Err(BomError.InvalidBuildQuantity)

    bom = await db.get(BillOfMaterials, bom_id)
    if bom is None:
        return Err(BomError.NotFound)

    rows = (
        await db.execute(
            select(BomMaterialLine, InventoryItem)
            .join(InventoryItem, BomMaterialLine.item_id == InventoryItem.id)
            .where(BomMaterialLine.bom_id == bom_id)
            .with_for_update(of=InventoryItem)
        )
    ).all()

    required: dict[UUID, int] = {}
    for material_line, item in rows:
        need = material_line.quantity_per_unit * build_quantity
        if item.quantity < need:
            return Err(BomError.InsufficientStock)
        required[item.id] = need

    reason_text = reason or f"BOM consumption: {bom.name} x{build_quantity}"
    adjustment_ids: list[UUID] = []
    for item_id, need in required.items():
        # The row is already locked (with_for_update above, same
        # transaction) -- adjust_item_quantity's own FOR UPDATE select on
        # the same row is a safe no-op re-lock, not a second real lock
        # attempt, so there's no race between the check above and this
        # write despite them being two separate statements.
        result = await adjust_item_quantity(
            db, item_id, -need, reason_text, adjusted_by
        )
        # Guaranteed Ok: stock was already verified sufficient above under
        # the same lock this write reuses -- an Err here would mean the
        # locking itself is broken, not a normal/expected outcome to
        # silently swallow.
        assert result.is_ok, (
            f"unexpected adjustment failure during BOM consume: {result}"
        )
        adjustment_ids.append(result.danger_ok)

    return Ok(adjustment_ids)
