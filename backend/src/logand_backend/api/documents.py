from __future__ import annotations

import argparse
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.app.config import AppConfig
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.documents import Document
from logand_backend.domain.documents.service import (
    create_document,
    delete_document,
    get_document,
    list_documents,
)
from logand_backend.domain.storage.factory import get_storage_backend

router = APIRouter(prefix="/api/admin/documents", tags=["admin", "documents"])

DocumentCategory = Literal["cad", "manual", "inventory", "documentation", "other"]

# Deliberately broader than budget/receipt evidence's image/PDF-only
# allowlist -- CAD files in particular are legitimately zip/step/dwg/etc,
# not something a fixed image/PDF allowlist should reject. Still an
# allowlist (not "anything goes"), just a wider one.
_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/zip",
    "application/octet-stream",
    "model/step",
    "application/sla",  # .stl
    "text/plain",
}


def _document_summary(document: Document) -> dict:
    return {
        "id": str(document.id),
        "title": document.title,
        "category": document.category,
        "tags": document.tags,
        "content_type": document.content_type,
        "inventory_item_id": str(document.inventory_item_id)
        if document.inventory_item_id
        else None,
        "created_at": document.created_at.isoformat(),
    }


@router.post("")
async def create(
    file: UploadFile,
    title: str,
    category: DocumentCategory,
    # Query(...), not a bare default -- list[str] silently drops out of
    # the route's parameter schema entirely (no 422, no error, just an
    # empty list every time) when a route also has an UploadFile param
    # unless it's explicitly marked Query() -- found by a real test
    # asserting tags actually round-tripped, not just that the request
    # returned 200.
    tags: list[str] | None = Query(default=None),
    inventory_item_id: UUID | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="unsupported file type")
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=422, detail="uploaded file is empty")

    result = await create_document(
        db,
        contents,
        file_path="",
        content_type=file.content_type,
        title=title,
        category=category,
        tags=tags,
        inventory_item_id=inventory_item_id,
    )
    if result.is_err:
        raise to_http_exception(result.danger_err)
    document_id = result.danger_ok

    # Same "patch file_path in after the id is known" pattern as
    # api/receipts.py -- see that route's doc comment.
    file_path = f"documents/{document_id}/{file.filename or 'file'}"
    document = await db.get(Document, document_id)
    assert document is not None
    document.file_path = file_path
    await db.flush()

    cfg = AppConfig.from_external(argparse.Namespace())
    storage = get_storage_backend(cfg)
    await storage.put(file_path, contents, file.content_type)

    return {"id": str(document_id)}


@router.get("")
async def list_all(
    category: DocumentCategory | None = None,
    tag: str | None = None,
    inventory_item_id: UUID | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await list_documents(
        db, category=category, tag=tag, inventory_item_id=inventory_item_id
    )
    return [_document_summary(row) for row in rows]


@router.get("/{document_id}/file")
async def download_file(
    document_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await get_document(db, document_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    document = result.danger_ok

    cfg = AppConfig.from_external(argparse.Namespace())
    storage = get_storage_backend(cfg)
    url = await storage.url(document.file_path)
    if url is not None:
        return RedirectResponse(url)
    data = await storage.get(document.file_path)
    return Response(content=data, media_type=document.content_type)


@router.delete("/{document_id}")
async def delete(
    document_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await delete_document(db, document_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "deleted"}
