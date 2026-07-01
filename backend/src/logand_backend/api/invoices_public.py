from __future__ import annotations

import argparse
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.auth.rate_limit import CUSTOMER_PAY, RateLimiter
from logand_backend.auth.sessions import SessionInfo, require_customer
from logand_backend.db.base import get_db
from logand_backend.db.models.invoices import Invoice

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
