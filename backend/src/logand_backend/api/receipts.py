from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.app.config import AppConfig
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.receipts import Receipt
from logand_backend.domain.receipts.service import (
    create_receipt,
    delete_receipt,
    get_receipt,
    list_receipts,
    reconcile_receipt,
)
from logand_backend.domain.storage.factory import get_storage_backend

router = APIRouter(prefix="/api/admin/receipts", tags=["admin", "receipts"])

_ALLOWED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg"}


def _receipt_summary(receipt: Receipt) -> dict:
    return {
        "id": str(receipt.id),
        "vendor": receipt.vendor,
        "amount": str(receipt.amount) if receipt.amount is not None else None,
        "category": receipt.category,
        "occurred_on": receipt.occurred_on.isoformat() if receipt.occurred_on else None,
        "note": receipt.note,
        "reconciled_budget_entry_id": str(receipt.reconciled_budget_entry_id)
        if receipt.reconciled_budget_entry_id
        else None,
        "captured_at": receipt.captured_at.isoformat(),
    }


@router.post("")
async def create(
    file: UploadFile,
    vendor: str | None = None,
    amount: Decimal | None = None,
    category: str | None = None,
    occurred_on: date | None = None,
    note: str | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """The ONLY required input is the photo/PDF itself -- every other
    field is optional (see db/models/receipts.py's Receipt doc comment).
    This is the deliberately minimal-friction endpoint the "snap a photo
    of the receipt" phone workflow calls: everything else can be filled
    in later via PATCH-equivalent reconcile/update flows once someone has
    time to actually categorize it.
    """
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="receipt must be a PDF or image")
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=422, detail="uploaded file is empty")

    # create_receipt assigns its own UUID internally, so the real
    # namespaced file_path (which wants that UUID) can't be known until
    # after it returns -- create with a placeholder path, then patch it in
    # once the real id exists, rather than adding a caller-supplied-id
    # parameter to create_receipt just for this one route.
    receipt_id = await create_receipt(
        db,
        contents,
        file_path="",
        vendor=vendor,
        amount=amount,
        category=category,
        occurred_on=occurred_on,
        note=note,
    )
    file_path = f"receipts/{receipt_id}/{file.filename or 'receipt'}"
    receipt = await db.get(Receipt, receipt_id)
    assert receipt is not None
    receipt.file_path = file_path
    await db.flush()

    cfg = AppConfig.from_external(argparse.Namespace())
    storage = get_storage_backend(cfg)
    await storage.put(file_path, contents, file.content_type)

    return {"id": str(receipt_id)}


@router.get("")
async def list_all(
    reconciled: bool | None = None,
    category: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await list_receipts(
        db,
        reconciled=reconciled,
        category=category,
        date_from=date_from,
        date_to=date_to,
    )
    return [_receipt_summary(row) for row in rows]


@router.get("/{receipt_id}/file")
async def download_file(
    receipt_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await get_receipt(db, receipt_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    receipt = result.danger_ok

    cfg = AppConfig.from_external(argparse.Namespace())
    storage = get_storage_backend(cfg)
    # Redirect to a real public URL when the backend has one (R2 with a
    # public custom domain) -- avoids proxying potentially large image/PDF
    # bytes through this server for no reason. Falls back to streaming the
    # bytes directly (LocalFilesystemStorage, or an R2 bucket with no
    # public access configured) when there isn't one.
    url = await storage.url(receipt.file_path)
    if url is not None:
        return RedirectResponse(url)
    data = await storage.get(receipt.file_path)
    return Response(content=data)


@router.post("/{receipt_id}/reconcile")
async def reconcile(
    receipt_id: UUID,
    budget_entry_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await reconcile_receipt(db, receipt_id, budget_entry_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "reconciled"}


@router.delete("/{receipt_id}")
async def delete(
    receipt_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await delete_receipt(db, receipt_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "deleted"}
