from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

import stripe
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Invoice, Payment, Refund
from logand_backend.domain.invoices.service import lock_invoice_for_update
from logand_backend.domain.notifications.notify import notify_refund_settled
from logand_backend.domain.payments.currency import to_minor_units
from logand_backend.domain.payments.providers import paypal
from logand_backend.errors import PaymentProviderError, RefundError
from logand_backend.logging import get_logger

_log = get_logger(__name__)

# Provider-reported refund statuses this app actually distinguishes,
# collapsed down to what db/models/invoices.py's _REFUND_STATUS_CHECK
# allows. A refund can come back "pending" (Stripe's own default for
# some payment methods, and PayPal's "PENDING") and later transition --
# see the charge.refund.updated handling in api/webhooks.py, which is
# the only thing that ever moves a Refund OUT of "pending".
STRIPE_REFUND_STATUS_MAP = {
    "succeeded": "succeeded",
    "failed": "failed",
    "canceled": "failed",
    "pending": "pending",
}
_PAYPAL_REFUND_STATUS_MAP = {
    "COMPLETED": "succeeded",
    "FAILED": "failed",
    "CANCELLED": "failed",
    "PENDING": "pending",
}


class RefundInput(BaseModel):
    model_config = {}

    payment_id: UUID
    # None means "refund the payment's full remaining balance" -- the
    # common case (an admin refunding one specific payment in full)
    # shouldn't require them to first look up and re-type the exact
    # remaining amount.
    amount: Decimal | None = None
    reason: str | None = None
    # Caller-generated (one per logical refund ACTION, e.g. one per admin
    # UI button click or one per API call site -- NOT regenerated on a
    # retry of that same action). This is the only thing that lets
    # refund_payment tell "the admin clicked refund a second time because
    # the first click's response never arrived" apart from "the admin
    # deliberately wants a second, distinct refund on this payment" --
    # both look identical from the server's side otherwise. It becomes
    # the Refund row's own id (and the provider idempotency key), so a
    # retry with the same value is recognized before any second provider
    # call is made. REQUIRED (not optional): an omitted value used to
    # mint a fresh id per call, which meant two concurrent calls for the
    # same payment could both pass the balance check and both reach the
    # provider with different idempotency keys, issuing two real refunds
    # for one payment (see M1 in FINDINGS.md history). Every caller must
    # generate one per logical action.
    client_request_id: UUID


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


async def _reserved_so_far(db: AsyncSession, payment_id: UUID) -> Decimal:
    """Like `_refunded_so_far`, but also counts still-`pending` refunds --
    money that hasn't settled yet but has already been claimed against
    this payment's balance. Used wherever a NEW refund is being
    validated against the remaining balance (M2): a pending refund must
    reserve its amount so a second refund request can't be validated
    against a balance that ignores it, even though (today) only the
    provider actually stops the resulting double-refund attempt.
    `_refunded_so_far` itself stays succeeded-only, since it also drives
    payment/invoice status transitions that should only fire once a
    refund has actually settled.
    """
    rows = (
        await db.execute(
            select(Refund).where(
                Refund.payment_id == payment_id,
                Refund.status.in_(("succeeded", "pending")),
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

    The invoice row is locked ONLY while validating and computing the
    amount to refund -- the lock is released (via an early commit)
    before any provider network call, so a slow/hung Stripe or PayPal
    round-trip never holds a DB connection and row lock for its
    duration. The Refund row (and any resulting payment/invoice status
    change) is then written in a short, freshly re-locked follow-up
    transaction. For a MANUAL refund (no stripe/paypal refund id) that
    follow-up transaction re-validates the balance, closing the window
    where two admins race a refund on the same invoice. For a
    provider-backed refund (stripe or paypal), the follow-up transaction
    does NOT re-validate the balance -- see `_record_refund`'s own
    comment -- so over-refund protection there rests entirely on the
    provider rejecting a refund that exceeds the charge's unrefunded
    balance (see FINDINGS.md L2).
    """
    existing = (
        await db.execute(select(Refund).where(Refund.id == refund.client_request_id))
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.payment_id != refund.payment_id
            or existing.invoice_id != invoice_id
        ):
            # The same client_request_id was reused for a DIFFERENT
            # payment/invoice than the one it was originally recorded
            # against -- a client bug (id reuse across distinct
            # actions), not a genuine retry. Returning the mismatched
            # existing.id here would silently report success for the
            # wrong refund; refuse instead of guessing.
            return Err(RefundError.PaymentNotFound)
        if existing.status == "failed":
            # The original attempt under this id recorded a FAILED
            # refund -- no money moved. Returning Ok(existing.id)
            # here (as a genuine retry normally does) would report
            # success for a refund that never happened. This is not
            # a satisfied retry; refuse it distinctly so the caller
            # can surface that no money was refunded and, if they
            # want to try again, must do so under a new
            # client_request_id (M3).
            return Err(RefundError.PriorAttemptFailed)
        # Retry of an action already recorded (the provider call, if
        # any, already happened under this same id) -- return the
        # prior outcome rather than evaluating/calling anything
        # again. This is the actual fix for H1: unlike a server-
        # generated uuid4() per invocation, this id is stable across
        # retries of the SAME logical action, so it is found here
        # instead of silently sailing through to a second provider
        # call.
        return Ok(existing.id)

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
    if payment.method == "stripe" and not payment.stripe_payment_intent_id:
        return Err(RefundError.ProviderReferenceMissing)
    if (
        payment.method == "paypal"
        and payment.paypal_order_id
        and not (payment.paypal_capture_id)
    ):
        return Err(RefundError.ProviderReferenceMissing)

    reserved_so_far = await _reserved_so_far(db, payment.id)
    remaining = payment.amount - reserved_so_far
    amount = refund.amount if refund.amount is not None else remaining
    if amount <= 0:
        return Err(RefundError.InvalidAmount)
    if amount > remaining:
        return Err(RefundError.AmountExceedsBalance)

    currency = invoice.currency
    is_stripe = payment.method == "stripe" and payment.stripe_payment_intent_id
    is_paypal = payment.method == "paypal" and payment.paypal_capture_id

    # The Refund row's id, and the provider idempotency key derived from
    # it. This IS the caller-supplied client_request_id -- stable across
    # a retry of the same logical action (the lookup above already
    # short-circuited a retry that arrives after the row exists; this
    # covers a retry that arrives WHILE the original call is still in
    # flight, or after the provider call succeeded but before
    # _record_refund committed -- the retry reaches the provider with the
    # same idempotency key and gets back the original refund rather than
    # creating a second one). client_request_id is required precisely so
    # this cross-request retry/concurrency safety always applies (M1).
    refund_id = refund.client_request_id
    idempotency_key = None
    if is_stripe or is_paypal:
        idempotency_key = f"refund:{refund_id}"

    # Release the invoice row lock (and this request's DB connection's
    # hold on it) BEFORE the provider network call -- see this
    # function's own doc comment (M1). A plain commit() is enough: the
    # AsyncSession auto-begins a new transaction on the next statement.
    await db.commit()

    stripe_refund_id: str | None = None
    paypal_refund_id: str | None = None
    refund_status = "succeeded"

    if is_stripe:
        _configure_stripe(cfg)
        try:
            stripe_refund = await asyncio.to_thread(
                stripe.Refund.create,
                payment_intent=payment.stripe_payment_intent_id,
                amount=to_minor_units(amount, currency),
                idempotency_key=idempotency_key,
            )
        except stripe.error.StripeError as exc:
            _log.error(
                "stripe refund failed",
                extra={"payment_id": str(payment.id)},
                exc_info=exc,
            )
            return Err(PaymentProviderError.RequestFailed)
        stripe_refund_id = stripe_refund.id
        refund_status = STRIPE_REFUND_STATUS_MAP.get(stripe_refund.status, "pending")
    elif is_paypal:
        result = await paypal.refund_capture(
            cfg,
            payment.paypal_capture_id,
            amount,
            currency,
            idempotency_key=idempotency_key,
        )
        if result.is_err:
            return Err(result.danger_err)
        paypal_refund_id = result.danger_ok.refund_id
        refund_status = _PAYPAL_REFUND_STATUS_MAP.get(
            result.danger_ok.status, "pending"
        )

    return await _record_refund(
        db,
        cfg=cfg,
        refund_id=refund_id,
        invoice_id=invoice_id,
        payment_id=payment.id,
        admin_id=admin_id,
        amount=amount,
        reason=refund.reason,
        status=refund_status,
        stripe_refund_id=stripe_refund_id,
        paypal_refund_id=paypal_refund_id,
    )


async def _record_refund(
    db: AsyncSession,
    *,
    cfg: AppConfig,
    refund_id: UUID,
    invoice_id: UUID,
    payment_id: UUID,
    admin_id: UUID,
    amount: Decimal,
    reason: str | None,
    status: str,
    stripe_refund_id: str | None,
    paypal_refund_id: str | None,
) -> Result[UUID, RefundError | PaymentProviderError]:
    """Short follow-up transaction: re-locks the invoice, re-validates the
    still-remaining balance (another refund may have landed on this
    payment during the provider round-trip), and writes the Refund row.

    The re-validation only matters for a provider call that was never
    actually made (stripe_refund_id/paypal_refund_id both None -- a
    manually-recorded refund, see refund_payment's own doc comment on
    "everything else"). Money already moved provider-side (stripe_refund_id
    or paypal_refund_id set) is never rejected here for "balance already
    covered" -- the refund happened regardless of what this row's INSERT
    does; rejecting it would silently drop a real refund from the ledger.
    A provider-backed over-refund can only happen if the PROVIDER itself
    allowed it, which is its own balance authority.
    """
    invoice = await lock_invoice_for_update(db, invoice_id)
    if invoice is None:
        # Should be unreachable (the invoice existed moments ago and
        # invoices are never hard-deleted) -- still record the refund so
        # a real provider-side refund is never silently dropped.
        invoice = None

    if stripe_refund_id is None and paypal_refund_id is None:
        # A concurrent retry sharing this same client_request_id (and
        # thus this same refund_id) may have already committed its own
        # Refund row while this call was serialized behind the invoice
        # re-lock above (L1). If so, this is a satisfied retry, not a
        # second refund competing for the same balance -- report the
        # prior outcome instead of re-validating against a balance that
        # now (correctly) includes that row and rejecting with a
        # confusing AmountExceedsBalance.
        already_recorded = (
            await db.execute(select(Refund).where(Refund.id == refund_id))
        ).scalar_one_or_none()
        if already_recorded is not None:
            await db.commit()
            return Ok(already_recorded.id)

        reserved_so_far = await _reserved_so_far(db, payment_id)
        payment_row = await db.get(Payment, payment_id)
        remaining = (
            payment_row.amount - reserved_so_far if payment_row is not None else None
        )
        if remaining is not None and amount > remaining:
            await db.commit()
            return Err(RefundError.AmountExceedsBalance)

    try:
        async with db.begin_nested():
            db.add(
                Refund(
                    id=refund_id,
                    payment_id=payment_id,
                    invoice_id=invoice_id,
                    amount=amount,
                    reason=reason,
                    stripe_refund_id=stripe_refund_id,
                    paypal_refund_id=paypal_refund_id,
                    status=status,
                    recorded_by=admin_id,
                )
            )
            await db.flush()
    except IntegrityError:
        # The common case: a retry that reused the same idempotency key
        # got the SAME provider-side refund id back -- the unique index
        # on stripe_refund_id/paypal_refund_id caught the duplicate
        # INSERT. The original attempt's row already recorded this
        # refund; nothing left for this call to do.
        existing = None
        if stripe_refund_id is not None or paypal_refund_id is not None:
            existing = (
                await db.execute(
                    select(Refund).where(
                        Refund.stripe_refund_id == stripe_refund_id
                        if stripe_refund_id is not None
                        else Refund.paypal_refund_id == paypal_refund_id
                    )
                )
            ).scalar_one_or_none()
        await db.commit()
        if existing is not None:
            return Ok(existing.id)
        # Not a duplicate-provider-id collision (some other constraint
        # violation, e.g. FK or a status check) -- and the provider call
        # (if any) has ALREADY executed by this point, so money may have
        # actually moved with no Refund row to show for it. Log loudly
        # rather than reporting a misleading "amount exceeds balance",
        # so this is never silently lost.
        _log.error(
            "refund row failed to record after a non-duplicate integrity "
            "error; provider refund may be unrecorded, investigate",
            extra={
                "payment_id": str(payment_id),
                "refund_id": str(refund_id),
                "stripe_refund_id": stripe_refund_id,
                "paypal_refund_id": paypal_refund_id,
            },
        )
        return Err(RefundError.RecordingFailed)

    payment = await db.get(Payment, payment_id)
    if status == "succeeded" and payment is not None:
        refunded_so_far = await _refunded_so_far(db, payment_id)
        payment.status = (
            "refunded" if refunded_so_far >= payment.amount else "partially_refunded"
        )
        await db.flush()

        # Invoice-level "refunded" only once total refunds across every
        # payment on the invoice cover the full amount_total -- the
        # mirror image of settle_invoice_if_paid's "sum succeeded
        # payments" check. A partial refund, or a full refund of just
        # one of several payments on a multi-payment invoice, leaves the
        # invoice "paid" (the customer did pay it in full; some of that
        # has since been returned, which is exactly what Payment.status/
        # Refund rows are for tracking, without overloading
        # Invoice.status to mean something murkier like "at least one
        # refund exists somewhere").
        if invoice is not None and invoice.status == "paid":
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

    await db.commit()

    # A refund the provider reports "succeeded" synchronously (the common
    # Stripe case) needs to notify the CUSTOMER here -- apply_refund_
    # settlement only covers the async path (a "pending" refund settling
    # later, e.g. via webhook or PayPal reconciliation) and is never
    # reached when the provider already resolved it inline. Without this,
    # a synchronously-settled refund silently emails no one while an
    # identical refund that happens to settle asynchronously does (see
    # FINDINGS.md L2). apply_refund_settlement only fires on a transition
    # OUT of "pending", so there is no risk of double-sending here.
    if status == "succeeded" and invoice is not None:
        await notify_refund_settled(db, cfg, invoice, amount)

    return Ok(refund_id)


async def apply_refund_settlement(
    db: AsyncSession, cfg: AppConfig, refund: Refund, mapped_status: str
) -> None:
    """Flips a "pending" Refund row to a now-terminal status and, only on
    a transition INTO "succeeded", applies the same payment/invoice
    status updates refund_payment itself would have made had the
    provider reported "succeeded" immediately. Shared by every path that
    can observe a pending refund settle:

    - api/webhooks.py's Stripe charge.refund.updated handler (push).
    - reconcile_pending_paypal_refunds below (poll -- PayPal delivers no
      webhook this app subscribes to for refund completion).

    Idempotent: a refund already out of "pending" is a no-op, so a
    duplicate webhook delivery racing a reconciliation poll (or two
    overlapping reconciliation runs) can never double-apply. Caller is
    responsible for having the Refund row locked (`with_for_update`)
    before calling this, same as both current callers do.
    """
    if refund.status != "pending":
        return
    refund.status = mapped_status
    await db.flush()
    if mapped_status != "succeeded":
        return

    payment = await db.get(Payment, refund.payment_id)
    if payment is None:
        return
    refunded_so_far = await _refunded_so_far(db, payment.id)
    payment.status = (
        "refunded" if refunded_so_far >= payment.amount else "partially_refunded"
    )
    await db.flush()

    invoice = (
        await db.execute(
            select(Invoice).where(Invoice.id == refund.invoice_id).with_for_update()
        )
    ).scalar_one_or_none()
    if invoice is not None and invoice.status == "paid":
        total_refunded_on_invoice = (
            await db.execute(
                select(func.coalesce(func.sum(Refund.amount), 0)).where(
                    Refund.invoice_id == invoice.id, Refund.status == "succeeded"
                )
            )
        ).scalar_one()
        if total_refunded_on_invoice >= invoice.amount_total:
            invoice.status = "refunded"
            await db.flush()

    if invoice is not None:
        # Release the invoice/refund row locks before the notification
        # email send -- same early-commit-before-external-I/O pattern
        # used elsewhere in this function (its own M1 doc comment) and
        # for the analogous dispute fan-out (FINDINGS.md M1).
        await db.commit()
        await notify_refund_settled(db, cfg, invoice, refund.amount)


async def reconcile_pending_paypal_refunds(db: AsyncSession, cfg: AppConfig) -> int:
    """Polls PayPal for every Refund row still "pending" and settles any
    that have since completed/failed -- see apply_refund_settlement's own
    doc comment for why this exists at all (no PayPal webhook is wired
    up). Run once daily by scripts/scheduler.py, same cadence as its
    other housekeeping jobs; safe to also run by hand for a manual
    catch-up, same convention as generate_recurring_invoices.py.

    Returns the number of refunds actually transitioned out of
    "pending" -- purely for the caller's own logging, not used for
    control flow.
    """
    if not paypal.is_configured(cfg):
        return 0

    pending_ids = (
        (
            await db.execute(
                select(Refund.id).where(
                    Refund.status == "pending", Refund.paypal_refund_id.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )

    settled_count = 0
    for refund_id in pending_ids:
        # Re-fetch and lock one row at a time (rather than locking the
        # whole pending set up front) -- each refund's PayPal round-trip
        # is independent, and a lock held across a network call for
        # every row in the batch would serialize this job behind however
        # slow PayPal's API happens to be that day, for no benefit.
        refund = (
            await db.execute(
                select(Refund).where(Refund.id == refund_id).with_for_update()
            )
        ).scalar_one_or_none()
        if (
            refund is None
            or refund.status != "pending"
            or refund.paypal_refund_id is None
        ):
            continue

        result = await paypal.get_refund_status(cfg, refund.paypal_refund_id)
        if result.is_err:
            _log.warning(
                "paypal refund reconciliation: status check failed",
                extra={"refund_id": str(refund.id)},
            )
            await db.commit()
            continue

        mapped_status = _PAYPAL_REFUND_STATUS_MAP.get(result.danger_ok.status)
        if mapped_status is None or mapped_status == "pending":
            await db.commit()
            continue

        await apply_refund_settlement(db, cfg, refund, mapped_status)
        await db.commit()
        settled_count += 1

    return settled_count
