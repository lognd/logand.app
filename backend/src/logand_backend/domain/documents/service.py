from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.models.documents import Document
from logand_backend.db.models.inventory import InventoryItem
from logand_backend.errors import DocumentError


async def create_document(
    db: AsyncSession,
    file_bytes: bytes,
    file_path: str,
    content_type: str,
    *,
    title: str,
    category: str,
    tags: list[str] | None = None,
    inventory_item_id: UUID | None = None,
) -> Result[UUID, DocumentError]:
    if inventory_item_id is not None:
        item = await db.get(InventoryItem, inventory_item_id)
        if item is None:
            return Err(DocumentError.InventoryItemNotFound)

    document_id = uuid4()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    db.add(
        Document(
            id=document_id,
            title=title,
            category=category,
            tags=tags or [],
            file_path=file_path,
            file_hash=file_hash,
            content_type=content_type,
            inventory_item_id=inventory_item_id,
        )
    )
    await db.flush()
    return Ok(document_id)


async def get_document(
    db: AsyncSession, document_id: UUID
) -> Result[Document, DocumentError]:
    document = await db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        return Err(DocumentError.NotFound)
    return Ok(document)


async def delete_document(
    db: AsyncSession, document_id: UUID
) -> Result[None, DocumentError]:
    document = await db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        return Err(DocumentError.NotFound)
    document.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return Ok(None)


async def list_documents(
    db: AsyncSession,
    *,
    category: str | None = None,
    tag: str | None = None,
    inventory_item_id: UUID | None = None,
) -> list[Document]:
    query = select(Document).where(Document.deleted_at.is_(None))
    if category is not None:
        query = query.where(Document.category == category)
    if tag is not None:
        # .contains([tag]), not .any(tag) -- same ambiguity/overload
        # reasoning as InventoryItem's search_items query.
        query = query.where(Document.tags.contains([tag]))
    if inventory_item_id is not None:
        query = query.where(Document.inventory_item_id == inventory_item_id)
    rows = (
        (await db.execute(query.order_by(Document.created_at.desc()))).scalars().all()
    )
    return list(rows)
