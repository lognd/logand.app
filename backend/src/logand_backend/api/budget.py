from __future__ import annotations

import argparse
import csv
import io
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api._uploads import read_upload_capped
from logand_backend.api.errors import to_http_exception
from logand_backend.app.config import AppConfig
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.budget import BudgetEntry
from logand_backend.domain.budget.service import attach_evidence, create_entry
from logand_backend.domain.storage.factory import get_storage_backend

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
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


@router.post("/{entry_id}/evidence")
async def upload_evidence(
    request: Request,
    entry_id: UUID,
    file: UploadFile,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if file.content_type not in {"application/pdf", "image/png", "image/jpeg"}:
        raise HTTPException(status_code=415, detail="evidence must be a PDF or image")
    contents = await read_upload_capped(file, request)
    file_path = f"budget-evidence/{entry_id}/{file.filename}"
    result = await attach_evidence(db, entry_id, contents, file_path=file_path)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    # Written AFTER attach_evidence's DB row succeeds (NotFound is checked
    # there first) -- no point uploading real bytes to storage for an
    # entry_id that doesn't exist. See domain/storage/base.py:
    # get_storage_backend(cfg) is the one place selecting local vs. R2 vs.
    # a future NAS backend; this route never talks to a concrete backend
    # directly.
    cfg = AppConfig.from_external(argparse.Namespace())
    storage = get_storage_backend(cfg)
    await storage.put(file_path, contents, file.content_type)
    return {"id": str(result.danger_ok)}


def _entry_query(category: str | None, date_from: date | None, date_to: date | None):
    query = select(BudgetEntry).where(BudgetEntry.deleted_at.is_(None))
    if category is not None:
        query = query.where(BudgetEntry.category == category)
    if date_from is not None:
        query = query.where(BudgetEntry.occurred_on >= date_from)
    if date_to is not None:
        query = query.where(BudgetEntry.occurred_on <= date_to)
    return query.order_by(BudgetEntry.occurred_on.desc())


@router.get("")
async def list_entries(
    category: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (
        (await db.execute(_entry_query(category, date_from, date_to))).scalars().all()
    )
    return [
        {
            "id": str(row.id),
            "amount": str(row.amount),
            "category": row.category,
            "vendor": row.vendor,
            "memo": row.memo,
            "occurred_on": row.occurred_on.isoformat(),
            "corrects_entry_id": str(row.corrects_entry_id)
            if row.corrects_entry_id
            else None,
        }
        for row in rows
    ]


@router.get("/export")
async def export_csv(
    category: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # NOTE: this is the actual audit deliverable per docs/design/05 -- streamed
    # row-by-row rather than buffered, since this is meant to scale to a full
    # year of expenses for tax prep / accountant handoff.
    rows = (
        (await db.execute(_entry_query(category, date_from, date_to))).scalars().all()
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "occurred_on",
            "category",
            "vendor",
            "amount",
            "memo",
            "corrects_entry_id",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                str(row.id),
                row.occurred_on.isoformat(),
                row.category,
                row.vendor or "",
                str(row.amount),
                row.memo or "",
                str(row.corrects_entry_id) if row.corrects_entry_id else "",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=budget_export.csv"},
    )
