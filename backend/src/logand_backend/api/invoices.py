from __future__ import annotations

import argparse
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.app.config import AppConfig
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.invoices import Invoice, InvoiceLineItem, Payment, Refund
from logand_backend.domain.invoices.pdf.renderer import PdfRenderError
from logand_backend.domain.invoices.refunds import RefundInput, refund_payment
from logand_backend.domain.invoices.service import (
    LineItemInput,
    ManualPaymentInput,
    create_invoice,
    generate_invoice_pdf,
    get_payment_proof,
    list_payment_proofs,
    record_manual_payment,
    send_invoice,
    void_invoice,
)
from logand_backend.domain.invoices.stats import InvoiceStats, get_invoice_stats
from logand_backend.domain.notifications.notify import (
    notify_invoice_sent,
    notify_payment_received,
)
from logand_backend.domain.storage.factory import get_storage_backend
from logand_backend.logging import get_logger

_log = get_logger(__name__)

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
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
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
    invoice = await db.get(Invoice, invoice_id)
    if invoice is not None:
        # Release the invoice row lock (taken inside send_invoice) before
        # the SMTP/Gmail send, same reasoning as invoices_public.py's
        # capture path: expire_on_commit=False keeps invoice.* readable
        # after commit, so this doesn't cost us anything but avoids
        # blocking concurrent payment/webhook processing on this row for
        # the duration of the notification send.
        await db.commit()
        cfg = AppConfig.from_external(argparse.Namespace())
        await notify_invoice_sent(db, cfg, invoice)
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


@router.get("/stats")
async def get_stats(
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InvoiceStats:
    # Declared before GET /{invoice_id} -- Starlette matches routes in
    # registration order, and "/{invoice_id}" would otherwise swallow
    # "/stats" as a literal (invalid) invoice_id first.
    return await get_invoice_stats(db)


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
    refunds = (
        (await db.execute(select(Refund).where(Refund.invoice_id == invoice_id)))
        .scalars()
        .all()
    )
    refunded_by_payment: dict[UUID, list[dict]] = {}
    for r in refunds:
        refunded_by_payment.setdefault(r.payment_id, []).append(
            {
                "id": str(r.id),
                "amount": str(r.amount),
                "reason": r.reason,
                "status": r.status,
                "stripe_refund_id": r.stripe_refund_id,
                "paypal_refund_id": r.paypal_refund_id,
                "recorded_by": str(r.recorded_by),
                "created_at": r.created_at.isoformat(),
            }
        )

    return {
        **_invoice_summary(invoice),
        "line_items": [
            {
                "id": str(li.id),
                "description": li.description,
                "quantity": str(li.quantity),
                "unit_price": str(li.unit_price),
                "unit": li.unit,
            }
            for li in line_items
        ],
        "payments": [
            {
                "id": str(p.id),
                "method": p.method,
                "amount": str(p.amount),
                "status": p.status,
                "transaction_id": p.transaction_id,
                "note": p.note,
                "recorded_by": str(p.recorded_by) if p.recorded_by else None,
                "dispute_status": p.dispute_status,
                "refunds": refunded_by_payment.get(p.id, []),
            }
            for p in payments
        ],
    }


@router.post("/{invoice_id}/payments/manual")
async def record_manual_invoice_payment(
    invoice_id: UUID,
    payment: ManualPaymentInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await record_manual_payment(db, invoice_id, admin.user_id, payment)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    invoice = await db.get(Invoice, invoice_id)
    if invoice is not None:
        # Release the invoice row lock (taken inside record_manual_payment)
        # before the notification send -- mirrors invoices_public.py's
        # capture path so a slow SMTP/Gmail send doesn't block a
        # concurrent customer self-serve payment or webhook on this row.
        await db.commit()
        cfg = AppConfig.from_external(argparse.Namespace())
        await notify_payment_received(db, cfg, invoice, payment.amount)
    return {"id": str(result.danger_ok)}


@router.post("/{invoice_id}/payments/{payment_id}/refund")
async def refund_invoice_payment(
    invoice_id: UUID,
    payment_id: UUID,
    body: RefundInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if body.payment_id != payment_id:
        raise HTTPException(
            status_code=422, detail="payment_id in body must match the URL"
        )
    cfg = AppConfig.from_external(argparse.Namespace())
    result = await refund_payment(db, cfg, invoice_id, admin.user_id, body)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


@router.get("/{invoice_id}/pdf")
async def get_invoice_pdf(
    invoice_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # No ownership check here (unlike invoices_public.py's identical
    # route) -- an admin can generate a PDF for any customer's invoice,
    # by design.
    cfg = AppConfig.from_external(argparse.Namespace())
    try:
        result = await generate_invoice_pdf(db, invoice_id, cfg)
    except PdfRenderError as exc:
        _log.error("invoice PDF generation failed", extra={"log": exc.log})
        raise HTTPException(
            status_code=500, detail="failed to generate invoice PDF"
        ) from exc
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return Response(
        content=result.danger_ok,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="invoice-{invoice_id}.pdf"'},
    )


@router.get("/{invoice_id}/payment-proof")
async def list_payment_proof(
    invoice_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """What an admin sees next to the manual-payment form -- every
    screenshot/receipt a customer has uploaded for this invoice, so
    there's something real to go on when deciding whether to record the
    payment."""
    result = await list_payment_proofs(db, invoice_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return [
        {
            "id": str(p.id),
            "content_type": p.content_type,
            "created_at": p.created_at.isoformat(),
        }
        for p in result.danger_ok
    ]


@router.get("/{invoice_id}/payment-proof/{proof_id}/file")
async def download_payment_proof(
    invoice_id: UUID,
    proof_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await get_payment_proof(db, invoice_id, proof_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    proof = result.danger_ok

    cfg = AppConfig.from_external(argparse.Namespace())
    storage = get_storage_backend(cfg)
    url = await storage.url(proof.file_path)
    if url is not None:
        return RedirectResponse(url)
    data = await storage.get(proof.file_path)
    return Response(content=data, media_type=proof.content_type)
