from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.domain.invoices.service import (
    LineItemInput,
    create_invoice,
    send_invoice,
    void_invoice,
)

router = APIRouter(prefix="/api/admin/invoices", tags=["admin", "invoices"])


@router.post("")
async def create(
    customer_id: UUID,
    line_items: list[LineItemInput],
    memo: str | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await create_invoice(db, customer_id, line_items, memo)
    if result.is_err:
        raise to_http_exception(result.err)
    return {"id": str(result.ok)}


@router.post("/{invoice_id}/send")
async def send(
    invoice_id: UUID, _admin: SessionInfo = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    result = await send_invoice(db, invoice_id)
    if result.is_err:
        raise to_http_exception(result.err)
    return {"status": "sent"}


@router.post("/{invoice_id}/void")
async def void(
    invoice_id: UUID, _admin: SessionInfo = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    result = await void_invoice(db, invoice_id)
    if result.is_err:
        raise to_http_exception(result.err)
    return {"status": "void"}


@router.get("")
async def list_invoices(
    status: str | None = None,
    customer_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    raise NotImplementedError("list/filter query; needs db.models.invoices")


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: UUID, _admin: SessionInfo = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    raise NotImplementedError("full detail incl. payments; needs db.models.invoices")
