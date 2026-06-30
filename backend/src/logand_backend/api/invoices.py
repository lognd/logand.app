from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.invoices import Invoice, InvoiceLineItem, Payment
from logand_backend.domain.invoices.service import (
    LineItemInput,
    create_invoice,
    send_invoice,
    void_invoice,
)

router = APIRouter(prefix="/api/admin/invoices", tags=["admin", "invoices"])


def _invoice_summary(invoice: Invoice) -> dict:
    return {
        "id": str(invoice.id),
        "customer_id": str(invoice.customer_id),
        "status": invoice.status,
        "amount_total": str(invoice.amount_total),
        "currency": invoice.currency,
        "memo": invoice.memo,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "is_recurring": invoice.is_recurring,
    }


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
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


@router.post("/{invoice_id}/send")
async def send(
    invoice_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await send_invoice(db, invoice_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "sent"}


@router.post("/{invoice_id}/void")
async def void(
    invoice_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await void_invoice(db, invoice_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
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
    query = select(Invoice).where(Invoice.deleted_at.is_(None))
    if status is not None:
        query = query.where(Invoice.status == status)
    if customer_id is not None:
        query = query.where(Invoice.customer_id == customer_id)
    if date_from is not None:
        query = query.where(Invoice.due_date >= date_from)
    if date_to is not None:
        query = query.where(Invoice.due_date <= date_to)
    rows = (await db.execute(query.order_by(Invoice.created_at.desc()))).scalars().all()
    return [_invoice_summary(row) for row in rows]


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    invoice = (
        await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one_or_none()
    if invoice is None or invoice.deleted_at is not None:
        raise HTTPException(status_code=404, detail="invoice not found")

    line_items = (
        (
            await db.execute(
                select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
            )
        )
        .scalars()
        .all()
    )
    payments = (
        (await db.execute(select(Payment).where(Payment.invoice_id == invoice_id)))
        .scalars()
        .all()
    )

    return {
        **_invoice_summary(invoice),
        "line_items": [
            {
                "id": str(li.id),
                "description": li.description,
                "quantity": str(li.quantity),
                "unit_price": str(li.unit_price),
            }
            for li in line_items
        ],
        "payments": [
            {
                "id": str(p.id),
                "amount": str(p.amount),
                "status": p.status,
                "transaction_id": p.transaction_id,
            }
            for p in payments
        ],
    }
