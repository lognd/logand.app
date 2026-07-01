from __future__ import annotations

import argparse
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.app.config import AppConfig
from logand_backend.auth.rate_limit import CUSTOMER_PAY, RateLimiter
from logand_backend.auth.sessions import SessionInfo, require_customer
from logand_backend.db.base import get_db
from logand_backend.db.models.invoices import Invoice
from logand_backend.domain.invoices.pdf.renderer import PdfRenderError
from logand_backend.domain.invoices.service import generate_invoice_pdf
from logand_backend.logging import get_logger

_log = get_logger(__name__)

router = APIRouter(prefix="/api/invoices", tags=["customer", "invoices"])
# redis_url wired from config -- see api/auth.py's identical NOTE for why
# this previously always used RateLimiter's in-process fallback regardless
# of REDIS_URL, and why AppConfig.redis_url defaulting to None (rather than
# a hardcoded-looking-real URL) matters here.
_pay_limiter = RateLimiter(
    *CUSTOMER_PAY, redis_url=AppConfig.from_external(argparse.Namespace()).redis_url
)


def _invoice_summary(invoice: Invoice) -> dict:
    return {
        "id": str(invoice.id),
        "status": invoice.status,
        "amount_total": str(invoice.amount_total),
        "currency": invoice.currency,
        "memo": invoice.memo,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
    }


@router.get("")
async def list_my_invoices(
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    # NOTE: WHERE customer_id = customer.user_id always -- never accept a
    # customer_id from the request, see docs/design/04 ownership isolation.
    query = select(Invoice).where(
        Invoice.customer_id == customer.user_id, Invoice.deleted_at.is_(None)
    )
    rows = (await db.execute(query.order_by(Invoice.created_at.desc()))).scalars().all()
    return [_invoice_summary(row) for row in rows]


async def _get_owned_invoice(
    db: AsyncSession, invoice_id: UUID, customer_id: UUID
) -> Invoice:
    invoice = (
        await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one_or_none()
    # NOTE: 404 (not 403) whether the invoice doesn't exist OR exists but
    # isn't owned by this customer -- never let the response distinguish the
    # two (docs/design/04).
    if (
        invoice is None
        or invoice.deleted_at is not None
        or invoice.customer_id != customer_id
    ):
        raise HTTPException(status_code=404, detail="invoice not found")
    return invoice


@router.get("/{invoice_id}")
async def get_my_invoice(
    invoice_id: UUID,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    invoice = await _get_owned_invoice(db, invoice_id, customer.user_id)
    return _invoice_summary(invoice)


@router.get("/{invoice_id}/pdf")
async def get_my_invoice_pdf(
    invoice_id: UUID,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # _get_owned_invoice (not generate_invoice_pdf's own NotFound check)
    # is what actually enforces ownership here -- generate_invoice_pdf
    # takes a bare invoice_id and doesn't know who's asking, by design
    # (it's shared with the admin route below, which has no ownership
    # restriction at all). This 404s on someone else's invoice before
    # ever reaching the PDF-generation step.
    await _get_owned_invoice(db, invoice_id, customer.user_id)
    cfg = AppConfig.from_external(argparse.Namespace())
    try:
        result = await generate_invoice_pdf(db, invoice_id, cfg)
    except PdfRenderError as exc:
        # The LaTeX compiler's own log is exactly what a real failure
        # (e.g. a LaTeX toolchain package missing from the deployed
        # image) needs to actually diagnose -- logged server-side, never
        # returned to the client (it's compiler internals, not something
        # a customer/admin should have to read to understand "PDF
        # generation failed").
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


@router.post("/{invoice_id}/pay")
async def pay_invoice(
    invoice_id: UUID,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _pay_limiter.check("invoice_pay", str(customer.user_id))
    invoice = await _get_owned_invoice(db, invoice_id, customer.user_id)
    if invoice.status not in ("sent", "overdue"):
        raise HTTPException(
            status_code=409, detail="invoice is not payable in its current state"
        )

    # NOTE: card data never touches this server -- Stripe Checkout/PaymentIntents
    # handles capture entirely on Stripe's side, see docs/design/04.
    cfg = AppConfig.from_external(argparse.Namespace())
    stripe.api_key = cfg.payment_processor_secret
    # None in production (stripe-python's own default: real api.stripe.com)
    # -- only set in test/CI, pointing at testing/fake_stripe.py's local
    # HTTP double, see AppConfig.stripe_api_base's doc comment.
    if cfg.stripe_api_base:
        stripe.api_base = cfg.stripe_api_base
    intent = stripe.PaymentIntent.create(
        amount=int(invoice.amount_total * 100),
        currency=invoice.currency,
        metadata={"invoice_id": str(invoice.id)},
    )
    invoice.stripe_payment_intent_id = intent.id
    await db.flush()
    # client_secret is only None for an already-confirmed/cancelled intent,
    # which a freshly created intent never is.
    assert intent.client_secret is not None
    return {"client_secret": intent.client_secret}
