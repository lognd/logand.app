from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.domain.budget.service import attach_evidence, create_entry

router = APIRouter(prefix="/api/admin/budget", tags=["admin", "budget"])


@router.post("")
async def create(
    amount: Decimal,
    category: str,
    occurred_on: date,
    vendor: str | None = None,
    memo: str | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await create_entry(db, amount, category, occurred_on, vendor, memo)
    if result.is_err:
        raise to_http_exception(result.err)
    return {"id": str(result.ok)}


@router.post("/{entry_id}/evidence")
async def upload_evidence(
    entry_id: UUID,
    file: UploadFile,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if file.content_type not in {"application/pdf", "image/png", "image/jpeg"}:
        raise HTTPException(status_code=415, detail="evidence must be a PDF or image")
    contents = await file.read()
    result = await attach_evidence(db, entry_id, contents, file_path=f"budget/{entry_id}/{file.filename}")
    if result.is_err:
        raise to_http_exception(result.err)
    return {"id": str(result.ok)}


@router.get("")
async def list_entries(
    category: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    raise NotImplementedError("list/filter query; needs db.models.budget")


@router.get("/export")
async def export_csv(_admin: SessionInfo = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    # NOTE: this is the actual audit deliverable per docs/design/05 -- do not
    # treat as an afterthought once db.models.budget exists. Should stream a
    # StreamingResponse with text/csv, not buffer the whole export in memory.
    raise NotImplementedError("CSV export; needs db.models.budget")
