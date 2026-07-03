from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import stripe
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Payment, Refund
from logand_backend.domain.invoices.service import lock_invoice_for_update
from logand_backend.domain.payments.providers import paypal
from logand_backend.errors import PaymentProviderError, RefundError
from logand_backend.logging import get_logger

_log = get_logger(__name__)


class RefundInput(BaseModel):
    model_config = {}

    payment_id: UUID
    # None means "refund the payment's full remaining balance" -- the
    # common case (an admin refunding one specific payment in full)
    # shouldn't require them to first look up and re-type the exact
    # remaining amount.
    amount: Decimal | None = None
    reason: str | None = None


def _configure_stripe(cfg: AppConfig) -> None:
    stripe.api_key = cfg.payment_processor_secret
    if cfg.stripe_api_base:
        stripe.api_base = cfg.stripe_api_base


async def _refunded_so_far(db: AsyncSession, payment_id: UUID) -> Decimal:
    rows = (
        await db.execute(
            select(Refund).where(
                Refund.payment_id == payment_id, Refund.status == "succeeded"
            )
        )
    ).scalars()
    return sum((r.amount for r in rows), Decimal(0))


async def refund_payment(
    db: AsyncSession,
    cfg: AppConfig,
    invoice_id: UUID,
    admin_id: UUID,
    refund: RefundInput,
) -> Result[UUID, RefundError | PaymentProviderError]:
    """Issues a refund (full or partial) against one Payment on an
    invoice. Method-aware:

    - stripe: calls stripe.Refund.create against the payment's own
      PaymentIntent -- Stripe handles the actual money movement.
    - paypal WITH a paypal_capture_id (a real Orders API payment): calls
      PayPal's refund-capture endpoint.
    - everything else (zelle/in_person/other, or a manually-recorded
      paypal payment with no paypal_capture_id): pure bookkeeping -- the
      admin already returned the money outside this system, this just
      records that it happened, same reasoning as record_manual_payment
      never calling a provider API.

    A payment can be refunded across more than one call (a partial
    refund now, another later); this always refunds against the
    payment's REMAINING balance (amount minus every prior succeeded
    Refund), never re-derives from the invoice total.
    """
    invoice = await lock_invoice_for_update(db, invoice_id)
    if invoice is None or invoice.deleted_at is not None:
        return Err(RefundError.PaymentNotFound)

    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == refund.payment_id, Payment.invoice_id == invoice_id
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        return Err(RefundError.PaymentNotFound)
    if payment.status not in ("succeeded", "partially_refunded"):
        return Err(RefundError.PaymentNotRefundable)

    refunded_so_far = await _refunded_so_far(db, payment.id)
    remaining = payment.amount - refunded_so_far
    amount = refund.amount if refund.amount is not None else remaining
    if amount <= 0:
        return Err(RefundError.InvalidAmount)
    if amount > remaining:
        return Err(RefundError.AmountExceedsBalance)

    stripe_refund_id: str | None = None
    paypal_refund_id: str | None = None

    if payment.method == "stripe" and payment.stripe_payment_intent_id:
        _configure_stripe(cfg)
        try:
            stripe_refund = await asyncio.to_thread(
                stripe.Refund.create,
                payment_intent=payment.stripe_payment_intent_id,
                amount=int(amount * 100),
            )
        except stripe.error.StripeError as exc:
            _log.error(
                "stripe refund failed",
                extra={"payment_id": str(payment.id)},
                exc_info=exc,
            )
            return Err(PaymentProviderError.RequestFailed)
        stripe_refund_id = stripe_refund.id
    elif payment.method == "paypal" and payment.paypal_capture_id:
        result = await paypal.refund_capture(
            cfg, payment.paypal_capture_id, amount, invoice.currency
        )
        if result.is_err:
            return Err(result.danger_err)
        paypal_refund_id = result.danger_ok.refund_id

    refund_id = uuid4()
    db.add(
        Refund(
            id=refund_id,
            payment_id=payment.id,
            invoice_id=invoice_id,
            amount=amount,
            reason=refund.reason,
            stripe_refund_id=stripe_refund_id,
            paypal_refund_id=paypal_refund_id,
            status="succeeded",
            recorded_by=admin_id,
        )
    )

    total_refunded = refunded_so_far + amount
    payment.status = (
        "refunded" if total_refunded >= payment.amount else "partially_refunded"
    )
    await db.flush()

    # Invoice-level "refunded" only once total refunds across every
    # payment on the invoice cover the full amount_total -- the mirror
    # image of settle_invoice_if_paid's "sum succeeded payments" check.
    # A partial refund, or a full refund of just one of several payments
    # on a multi-payment invoice, leaves the invoice "paid" (the customer
    # did pay it in full; some of that has since been returned, which is
    # exactly what Payment.status/Refund rows are for tracking, without
    # overloading Invoice.status to mean something murkier like "at least
    # one refund exists somewhere").
    if invoice.status == "paid":
        refund_rows = (
            await db.execute(
                select(Refund).where(
                    Refund.invoice_id == invoice_id, Refund.status == "succeeded"
                )
            )
        ).scalars()
        total_refunded_on_invoice = sum((r.amount for r in refund_rows), Decimal(0))
        if total_refunded_on_invoice >= invoice.amount_total:
            invoice.status = "refunded"
            await db.flush()

    return Ok(refund_id)
