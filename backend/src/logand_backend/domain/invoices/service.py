from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import (
    Invoice,
    InvoiceLineItem,
    Payment,
    PaymentProof,
    Refund,
)
from logand_backend.domain.notifications.notify import notify_payment_received
from logand_backend.domain.payments import currency
from logand_backend.domain.payments.providers import paypal
from logand_backend.errors import InvoiceError
from logand_backend.logging import get_logger

_log = get_logger(__name__)

# Every method an admin can record BY HAND -- "stripe" is deliberately
# excluded (that one only ever gets created automatically, from a real
# Stripe webhook, see api/webhooks.py) and so is a real PayPal-API capture
# (domain/payments/providers/paypal.py creates its own Payment row once
# that's hooked up). "paypal" here means "the customer already sent a
# PayPal payment some other way (their own PayPal app, e.g.) and an admin
# is just recording that it happened" -- same `method` value either way,
# distinguished by paypal_order_id being set or not (see
# db/models/invoices.py's Payment.paypal_order_id doc comment).
ManualPaymentMethod = Literal["paypal", "zelle", "in_person", "other"]


class ManualPaymentInput(BaseModel):
    model_config = {}

    method: ManualPaymentMethod
    # Mirrors the refund guard (refunds.py: RefundError.InvalidAmount on
    # amount <= 0) -- see FINDINGS.md M-1. A non-positive amount here would
    # silently corrupt get_paid_so_far/get_amount_due and can send a
    # "received your payment of 0.00" email.
    amount: Decimal = Field(gt=0)
    note: str | None = None


class LineItemInput(BaseModel):
    model_config = {}

    description: str
    # See FINDINGS.md M-2: an unconstrained quantity/unit_price lets a
    # negative line silently corrupt the denormalized amount_total that
    # every downstream money calc trusts.
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    unit_price: Decimal = Field(ge=0)
    unit: str | None = None


async def lock_invoice_for_update(db: AsyncSession, invoice_id: UUID) -> Invoice | None:
    """SELECT ... FOR UPDATE on a single invoice row -- serializes any two
    concurrent requests that both try to read-then-mutate the SAME
    invoice (a double-clicked "send," two admins racing a manual payment,
    a retried webhook overlapping a customer's own /pay call) without
    taking any lock at all on OTHER invoices, so this has no throughput
    impact under normal traffic (a customer paying invoice A never blocks
    a completely unrelated payment against invoice B). Postgres releases
    the row lock automatically when this transaction commits or rolls
    back -- there's no separate unlock step to remember.

    Only used on paths that read a status/amount and then act on it
    (send/void/record-payment/pay); generate_invoice_pdf below is
    deliberately NOT locked, since it's read-only and taking a write lock
    there would serialize PDF downloads against payment operations for no
    reason.
    """
    return (
        await db.execute(
            select(Invoice).where(Invoice.id == invoice_id).with_for_update()
        )
    ).scalar_one_or_none()


async def recompute_amount_total(db: AsyncSession, invoice_id: UUID) -> Decimal:
    """Sums invoice_line_items for invoice_id and writes it back to
    invoices.amount_total in the same transaction. Called on every write
    path -- amount_total must never be trusted from client input
    (docs/design/04, the tamper vector this exists to close)."""
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        return Decimal(0)

    line_items = (
        await db.execute(
            select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
        )
    ).scalars()
    # Quantize each line total to the invoice's OWN currency's real
    # precision (0dp for JPY/KRW/..., 3dp for BHD/KWD/..., 2dp otherwise)
    # before summing -- must match InvoiceLineItemView.line_total's
    # rounding rule (export.py) exactly, otherwise amount_total (this
    # column) can disagree with the sum of the per-line totals shown in
    # the PDF/email/attachments. See FINDINGS.md M1/L1.
    total = sum(
        (
            currency.quantize_to_currency(li.quantity * li.unit_price, invoice.currency)
            for li in line_items
        ),
        Decimal(0),
    )

    invoice.amount_total = total
    await db.flush()
    return total


async def create_invoice(
    db: AsyncSession,
    customer_id: UUID,
    line_items: list[LineItemInput],
    memo: str | None = None,
) -> Result[UUID, InvoiceError]:
    invoice_id = uuid4()
    invoice = Invoice(id=invoice_id, customer_id=customer_id, memo=memo, status="draft")
    db.add(invoice)
    # Flush now so the model's `currency` column default ("usd") is
    # actually populated on the instance -- it's a Python-side default
    # applied by SQLAlchemy at flush time, not at construction, so reading
    # invoice.currency before this point would be None.
    await db.flush()
    for item in line_items:
        db.add(
            InvoiceLineItem(
                id=uuid4(),
                invoice_id=invoice_id,
                description=item.description,
                quantity=item.quantity,
                # Quantize to the invoice's currency precision on write so
                # unit_price_display (export.py) always equals the stored
                # value and every line reconciles (qty * unit_price ==
                # line_total). See FINDINGS.md M1.
                unit_price=currency.quantize_to_currency(
                    item.unit_price, invoice.currency
                ),
                unit=item.unit,
            )
        )
    await db.flush()
    await recompute_amount_total(db, invoice_id)
    return Ok(invoice_id)


async def send_invoice(
    db: AsyncSession, invoice_id: UUID
) -> Result[None, InvoiceError]:
    """draft -> sent. Once sent, line items are frozen (docs/design/04) --
    enforce that here, not just in the API layer, since domain functions
    are the only thing that should be trusted to hold this invariant."""
    invoice = await lock_invoice_for_update(db, invoice_id)
    if invoice is None:
        return Err(InvoiceError.NotFound)
    if invoice.status != "draft":
        return Err(InvoiceError.InvalidState)
    # NOTE: "freezing" line items is enforced by never exposing a line-item
    # mutation path for non-draft invoices in api/invoices.py -- there is no
    # separate frozen flag on InvoiceLineItem to maintain here.
    invoice.status = "sent"
    await db.flush()
    return Ok(None)


async def void_invoice(
    db: AsyncSession, invoice_id: UUID
) -> Result[None, InvoiceError]:
    invoice = await lock_invoice_for_update(db, invoice_id)
    if invoice is None:
        return Err(InvoiceError.NotFound)
    if invoice.status not in ("sent", "overdue"):
        return Err(InvoiceError.InvalidState)
    invoice.status = "void"
    await db.flush()
    return Ok(None)


async def has_pending_payment(db: AsyncSession, invoice_id: UUID) -> bool:
    """True if a `Payment` row for `invoice_id` is currently `pending` -- a
    PayPal capture held for review (see M1 in FINDINGS.md). While one is
    outstanding, `get_paid_so_far`/`get_amount_due` still show the invoice
    as fully owed (pending contributes nothing to settlement math), so
    every payment-initiation path (`record_manual_payment`, `pay_invoice`,
    `pay_invoice_via_paypal`) must call this BEFORE letting a second
    payment start, or the pending capture clearing later double-collects.
    """
    existing = (
        await db.execute(
            select(Payment.id).where(
                Payment.invoice_id == invoice_id, Payment.status == "pending"
            )
        )
    ).scalar_one_or_none()
    return existing is not None


async def flag_invoice_needs_review(
    db: AsyncSession, invoice: Invoice, reason: str
) -> None:
    """Persists a durable, admin-facing "needs review" signal on `invoice`
    (see M2/L2 in FINDINGS.md) -- called from every place that detects a
    suspected double-collect/overpayment, which previously surfaced only
    as a warning log line nobody necessarily sees. Idempotent-ish: does
    not clear a previously-set flag, and if called more than once just
    overwrites the reason with the latest one (multiple flags on one
    invoice are rare enough that a single reason string is sufficient --
    the caller's own log line still records every individual occurrence).
    """
    invoice.needs_review = True
    invoice.needs_review_reason = reason
    await db.flush()


async def record_manual_payment(
    db: AsyncSession, invoice_id: UUID, admin_id: UUID, payment: ManualPaymentInput
) -> Result[UUID, InvoiceError]:
    """Records a payment an admin observed happening OUTSIDE this system
    -- a Zelle transfer, cash handed over in person, a PayPal payment sent
    directly customer-to-admin, or anything else that isn't the Stripe
    PaymentIntent flow (api/invoices_public.py's /pay). There is no
    provider API call here at all, by design: this is bookkeeping, not
    payment processing -- see docs/design/04 and this module's own
    ManualPaymentMethod doc comment for why "paypal" specifically can mean
    either this OR a real PayPal API capture depending on whether
    paypal_order_id ends up set.

    Marks the invoice "paid" only once recorded payments cover the full
    amount_total -- a partial manual payment (an admin recording a partial
    Zelle transfer, say) is still recorded for the record, but the invoice
    stays payable (sent/overdue) for the remaining balance rather than
    being incorrectly marked fully paid.
    """
    # lock_invoice_for_update (SELECT ... FOR UPDATE), not db.get -- two admins (or
    # one admin double-clicking Save) recording a payment against the
    # SAME invoice at the same moment must be serialized, or both could
    # read "$60 recorded so far, not yet covering the $100 total" before
    # either one's INSERT commits, and neither would flip the invoice to
    # "paid" even though the two payments together cover it (a lost
    # update -- the invoice would stay "sent" until someone noticed and
    # manually fixed it).
    invoice = await lock_invoice_for_update(db, invoice_id)
    if invoice is None or invoice.deleted_at is not None:
        return Err(InvoiceError.NotFound)
    if invoice.status not in ("sent", "overdue"):
        return Err(InvoiceError.InvalidState)
    if await has_pending_payment(db, invoice_id):
        return Err(InvoiceError.PaymentPending)

    payment_id = uuid4()
    db.add(
        Payment(
            id=payment_id,
            invoice_id=invoice_id,
            method=payment.method,
            amount=payment.amount,
            status="succeeded",
            recorded_by=admin_id,
            note=payment.note,
        )
    )
    await db.flush()

    await settle_invoice_if_paid(db, invoice)

    return Ok(payment_id)


async def get_paid_so_far(db: AsyncSession, invoice: Invoice) -> Decimal:
    """Sums the net amount still credited from every succeeded or
    partially-refunded `Payment` recorded against `invoice`. Shared by
    `settle_invoice_if_paid` and by the self-serve pay entry points
    (`api/invoices_public.py::pay_invoice` and `pay_invoice_via_paypal`) so
    both "is this invoice fully paid" and "how much is still owed" are
    derived from the same source of truth.

    A `partially_refunded` payment still contributes its unrefunded
    remainder (amount minus succeeded refunds against it) -- see M1 in
    FINDINGS.md, where counting only `succeeded` payments dropped a
    partially-refunded payment's entire amount instead of just the
    refunded portion. Fully `refunded` payments correctly contribute
    nothing and stay excluded.
    """
    refunded_by_payment = (
        select(
            Refund.payment_id.label("payment_id"),
            func.sum(Refund.amount).label("refunded"),
        )
        .where(Refund.status == "succeeded")
        .group_by(Refund.payment_id)
        .subquery()
    )
    net_paid = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        Payment.amount
                        - func.coalesce(refunded_by_payment.c.refunded, 0)
                    ),
                    0,
                )
            )
            .select_from(Payment)
            .outerjoin(
                refunded_by_payment,
                refunded_by_payment.c.payment_id == Payment.id,
            )
            .where(
                Payment.invoice_id == invoice.id,
                Payment.status.in_(("succeeded", "partially_refunded")),
            )
        )
    ).scalar_one()
    return Decimal(net_paid)


async def get_amount_due(db: AsyncSession, invoice: Invoice) -> Decimal:
    """Outstanding remainder on `invoice`: `amount_total` minus every
    succeeded payment recorded so far (manual, Stripe, or PayPal), floored
    at zero. Used to bill only what's actually still owed instead of
    always billing the full invoice total regardless of prior partial
    payments (see H1 in FINDINGS.md).
    """
    paid_so_far = await get_paid_so_far(db, invoice)
    remainder = invoice.amount_total - paid_so_far
    return remainder if remainder > 0 else Decimal(0)


async def settle_invoice_if_paid(db: AsyncSession, invoice: Invoice) -> bool:
    """Marks `invoice` "paid" once its succeeded payments cover
    `amount_total`. Shared by every path that can record a succeeded
    payment (manual recording here, the Stripe webhook's insert AND
    update-existing branches, the PayPal capture route) so "paid" is
    decided in exactly one place regardless of which path last touched
    the invoice's payments. Idempotent: a no-op if already paid or still
    short of the total. Returns True iff this call is what flipped it.
    """
    if invoice.status == "paid":
        return False
    paid_so_far = await get_paid_so_far(db, invoice)
    if paid_so_far >= invoice.amount_total:
        invoice.status = "paid"
        invoice.paid_at = datetime.now(timezone.utc)
        await db.flush()
        return True
    return False


async def reconcile_pending_paypal_captures(db: AsyncSession, cfg: AppConfig) -> int:
    """Polls PayPal for every Payment row still "pending" (a PayPal
    capture that came back PENDING at capture time -- e.g. held for
    review -- see M1 in FINDINGS.md and
    api/invoices_public.py::capture_invoice_paypal_payment) and settles
    any that have since resolved. Mirrors
    domain/invoices/refunds.py::reconcile_pending_paypal_refunds exactly:
    PayPal delivers no webhook this app subscribes to for capture
    completion either, so polling is the only way to ever learn the
    outcome. Run once daily by scripts/scheduler.py, same cadence as the
    refund reconciler; safe to also run by hand for a manual catch-up.

    Returns the number of payments actually transitioned out of
    "pending" -- purely for the caller's own logging, not used for
    control flow.
    """
    if not paypal.is_configured(cfg):
        return 0

    pending_ids = (
        (
            await db.execute(
                select(Payment.id).where(
                    Payment.method == "paypal",
                    Payment.status == "pending",
                    Payment.paypal_order_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    settled_count = 0
    for payment_id in pending_ids:
        # Re-fetch and lock one row at a time (rather than locking the
        # whole pending set up front) -- each payment's PayPal round-trip
        # is independent, and a lock held across a network call for
        # every row in the batch would serialize this job behind however
        # slow PayPal's API happens to be that day, for no benefit. Same
        # reasoning as reconcile_pending_paypal_refunds.
        payment = (
            await db.execute(
                select(Payment).where(Payment.id == payment_id).with_for_update()
            )
        ).scalar_one_or_none()
        if (
            payment is None
            or payment.status != "pending"
            or payment.paypal_order_id is None
        ):
            continue

        result = await paypal.get_order_status(cfg, payment.paypal_order_id)
        if result.is_err:
            _log.warning(
                "paypal capture reconciliation: status check failed",
                extra={"payment_id": str(payment.id)},
            )
            await db.commit()
            continue

        capture = result.danger_ok
        if capture.status == "PENDING":
            await db.commit()
            continue
        if capture.status != "COMPLETED":
            # Terminal non-success (DECLINED, VOIDED, ...) -- money never
            # arrived after all; mark the Payment failed so it stops
            # being polled and the invoice is left payable again.
            payment.status = "failed"
            await db.flush()
            await db.commit()
            settled_count += 1
            continue

        payment.status = "succeeded"
        await db.flush()

        invoice = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == payment.invoice_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if invoice is not None:
            # Check BEFORE settle_invoice_if_paid, which only ever flips
            # invoice.status -- it never changes what get_paid_so_far
            # sums, so the amount-due comparison is unaffected by call
            # order. Mirrors the synchronous capture route's own
            # overpayment log (api/invoices_public.py) for the case this
            # reconciler is uniquely exposed to: the invoice was already
            # paid another way (manual/Stripe/an earlier capture) while
            # this capture sat PENDING, so completing it now is real
            # double-collected money with no other signal raised.
            paid_so_far = await get_paid_so_far(db, invoice)
            if paid_so_far > invoice.amount_total:
                _log.warning(
                    "paypal reconciled capture overpays invoice; "
                    "recorded anyway, needs follow-up/refund",
                    extra={
                        "invoice_id": str(invoice.id),
                        "payment_id": str(payment.id),
                        "paid_so_far": str(paid_so_far),
                        "amount_total": str(invoice.amount_total),
                    },
                )
                await flag_invoice_needs_review(
                    db,
                    invoice,
                    "paypal reconciled capture overpays invoice "
                    f"(paid_so_far={paid_so_far}, amount_total={invoice.amount_total})",
                )
            await settle_invoice_if_paid(db, invoice)
            # Release the invoice/payment row locks before the
            # notification email send -- same early-commit-before-
            # external-I/O pattern used by the capture route itself and
            # by reconcile_pending_paypal_refunds's own doc comment.
            await db.commit()
            await notify_payment_received(db, cfg, invoice, payment.amount)
        else:
            await db.commit()
        settled_count += 1

    return settled_count


async def attach_payment_proof(
    db: AsyncSession,
    invoice_id: UUID,
    uploaded_by: UUID,
    file_bytes: bytes,
    file_path: str,
    content_type: str,
) -> Result[UUID, InvoiceError]:
    """A customer-uploaded screenshot/receipt showing they sent a manual
    payment -- deliberately NOT gated on invoice status the way
    record_manual_payment is: a customer uploads this hoping to speed up
    an admin marking the invoice paid, so it must work for a "sent" or
    "overdue" invoice (the whole point) but there's no reason to reject
    it for an already-"paid" invoice either (a late/duplicate upload is
    harmless, not an error). Only draft/void invoices -- which were never
    payable in the first place -- make no sense to attach proof to.
    """
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or invoice.deleted_at is not None:
        return Err(InvoiceError.NotFound)
    if invoice.status in ("draft", "void"):
        return Err(InvoiceError.InvalidState)

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    proof_id = uuid4()
    db.add(
        PaymentProof(
            id=proof_id,
            invoice_id=invoice_id,
            uploaded_by=uploaded_by,
            file_path=file_path,
            content_type=content_type,
            file_hash=file_hash,
        )
    )
    await db.flush()
    return Ok(proof_id)


async def list_payment_proofs(
    db: AsyncSession, invoice_id: UUID
) -> Result[list[PaymentProof], InvoiceError]:
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or invoice.deleted_at is not None:
        return Err(InvoiceError.NotFound)
    rows = (
        (
            await db.execute(
                select(PaymentProof)
                .where(PaymentProof.invoice_id == invoice_id)
                .order_by(PaymentProof.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return Ok(list(rows))


async def get_payment_proof(
    db: AsyncSession, invoice_id: UUID, proof_id: UUID
) -> Result[PaymentProof, InvoiceError]:
    proof = await db.get(PaymentProof, proof_id)
    if proof is None or proof.invoice_id != invoice_id:
        return Err(InvoiceError.NotFound)
    return Ok(proof)
