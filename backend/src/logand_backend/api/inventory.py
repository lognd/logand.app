from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.inventory import (
    InventoryAdjustment,
    InventoryItem,
    InventoryLocation,
)
from logand_backend.domain.inventory.service import (
    adjust_item_quantity,
    create_item,
    delete_item,
    list_item_adjustments,
    move_item,
    search_items,
    set_item_unit_cost,
    update_item_quantity,
)

router = APIRouter(prefix="/api/admin/inventory", tags=["admin", "inventory"])


class AdjustQuantityInput(BaseModel):
    model_config = {}

    # Signed -- +5 restocked, -3 sold/used/scrapped. Distinct from
    # PATCH /items/{id}'s quantity param (an absolute set-to-value, kept
    # around for the create/edit-item form); this is specifically the
    # audited "I'm changing the count by this much, here's why" path.
    delta: int
    reason: str


def _adjustment_summary(adj: InventoryAdjustment) -> dict:
    return {
        "id": str(adj.id),
        "delta": adj.delta,
        "quantity_before": adj.quantity_before,
        "quantity_after": adj.quantity_after,
        "reason": adj.reason,
        "adjusted_by": str(adj.adjusted_by) if adj.adjusted_by else None,
        "created_at": adj.created_at.isoformat(),
    }


def _item_summary(item: InventoryItem) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "quantity": item.quantity,
        "location_id": str(item.location_id),
        "tags": item.tags,
        "unit_cost": str(item.unit_cost) if item.unit_cost is not None else None,
    }


@router.post("/locations")
async def create_location(
    name: str,
    description: str | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    location_id = uuid4()
    db.add(InventoryLocation(id=location_id, name=name, description=description))
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="location name already exists"
        ) from exc
    return {"id": str(location_id)}


@router.get("/locations")
async def list_locations(
    _admin: SessionInfo = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    rows = (
        (await db.execute(select(InventoryLocation).order_by(InventoryLocation.name)))
        .scalars()
        .all()
    )
    return [
        {"id": str(row.id), "name": row.name, "description": row.description}
        for row in rows
    ]


@router.post("/items")
async def create(
    name: str,
    location_id: UUID,
    quantity: int = 1,
    description: str | None = None,
    tags: list[str] | None = None,
    unit_cost: Decimal | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await create_item(
        db, name, location_id, quantity, description, tags, unit_cost
    )
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


@router.patch("/items/{item_id}/unit-cost")
async def update_unit_cost(
    item_id: UUID,
    unit_cost: Decimal,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """A separate route (not folded into the general PATCH /items/{id}
    above) since setting a cost is a distinct, BOM-specific admin action
    with its own real meaning -- worth its own explicit endpoint rather
    than one more optional field on an already-multi-purpose PATCH."""
    result = await set_item_unit_cost(db, item_id, unit_cost)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "ok"}


@router.patch("/items/{item_id}")
async def update_item(
    item_id: UUID,
    location_id: UUID | None = None,
    quantity: int | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if location_id is not None:
        result = await move_item(db, item_id, location_id)
        if result.is_err:
            raise to_http_exception(result.danger_err)
    if quantity is not None:
        result = await update_item_quantity(db, item_id, quantity)
        if result.is_err:
            raise to_http_exception(result.danger_err)
    return {"status": "ok"}


@router.post("/items/{item_id}/adjust")
async def adjust_quantity(
    item_id: UUID,
    body: AdjustQuantityInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """The audited manual-adjustment path -- see
    domain/inventory/service.py::adjust_item_quantity's own doc comment.
    The frontend is expected to show the admin an explicit before-to-
    after confirmation (fetching the item's current quantity first) BEFORE
    calling this, per the site-wide "confirmations on everything,
    including UI" convention -- this endpoint itself has no separate
    confirm step of its own; that would just be a second network
    round-trip for a UI-layer requirement the frontend already owns.
    """
    result = await adjust_item_quantity(
        db, item_id, body.delta, body.reason, admin.user_id
    )
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


@router.get("/items/{item_id}/adjustments")
async def get_item_adjustments(
    item_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """The rollback/history view -- every past adjustment for one item,
    newest first, exact before/after values included."""
    result = await list_item_adjustments(db, item_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return [_adjustment_summary(adj) for adj in result.danger_ok]


@router.get("/items")
async def search(
    q: str | None = None,
    location_id: UUID | None = None,
    tag: str | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await search_items(db, q, location_id, tag)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return [_item_summary(item) for item in result.danger_ok]


@router.delete("/items/{item_id}")
async def delete(
    item_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await delete_item(db, item_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "deleted"}
