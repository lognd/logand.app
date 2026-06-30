from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.domain.inventory.service import create_item, move_item, search_items

router = APIRouter(prefix="/api/admin/inventory", tags=["admin", "inventory"])


@router.post("/locations")
async def create_location(
    name: str, description: str | None = None, _admin: SessionInfo = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    raise NotImplementedError("insert inventory_locations row; needs db.models.inventory")


@router.get("/locations")
async def list_locations(_admin: SessionInfo = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> list[dict]:
    raise NotImplementedError("list query; needs db.models.inventory")


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
        raise to_http_exception(result.err)
    return {"id": str(result.ok)}


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
            raise to_http_exception(result.err)
    raise NotImplementedError("quantity adjust path; needs db.models.inventory")


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
        raise to_http_exception(result.err)
    return []  # NOTE: result.ok is currently list[UUID]; needs hydration to full item dicts once db.models.inventory exists


@router.delete("/items/{item_id}")
async def delete_item(item_id: UUID, _admin: SessionInfo = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    raise NotImplementedError("hard delete; needs db.models.inventory")
