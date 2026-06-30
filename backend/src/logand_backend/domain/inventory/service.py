from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Result

from logand_backend.errors import InventoryError


async def create_item(
    db: AsyncSession, name: str, location_id: UUID, quantity: int = 1, description: str | None = None, tags: list[str] | None = None
) -> Result[UUID, InventoryError]:
    raise NotImplementedError("insert inventory_items row; needs db.models.inventory")


async def move_item(db: AsyncSession, item_id: UUID, new_location_id: UUID) -> Result[None, InventoryError]:
    raise NotImplementedError("update location_id; needs db.models.inventory")


async def search_items(
    db: AsyncSession, query: str | None = None, location_id: UUID | None = None, tag: str | None = None
) -> Result[list[UUID], InventoryError]:
    """Free-text `query` uses Postgres full-text search
    (to_tsvector('english', name || ' ' || coalesce(description, '')), GIN
    indexed) per docs/design/06 -- not ILIKE, that doesn't scale past a
    couple dozen items and we'd need a migration to switch later anyway."""
    raise NotImplementedError("ts_query search + filters; needs db.models.inventory")
