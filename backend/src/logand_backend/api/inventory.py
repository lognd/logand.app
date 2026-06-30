from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.inventory import InventoryItem, InventoryLocation
from logand_backend.domain.inventory.service import (
    create_item,
    delete_item,
    move_item,
    search_items,
    update_item_quantity,
)

router = APIRouter(prefix="/api/admin/inventory", tags=["admin", "inventory"])


def _item_summary(item: InventoryItem) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "quantity": item.quantity,
        "location_id": str(item.location_id),
        "tags": item.tags,
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
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await create_item(db, name, location_id, quantity, description, tags)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


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
