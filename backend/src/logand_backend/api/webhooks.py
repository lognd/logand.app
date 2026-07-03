from __future__ import annotations

import argparse

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.base import get_db
from logand_backend.db.models.invoices import Invoice, Payment, Refund
from logand_backend.domain.invoices.refunds import (
    STRIPE_REFUND_STATUS_MAP,
    apply_refund_settlement,
)
from logand_backend.domain.invoices.service import settle_invoice_if_paid
from logand_backend.domain.notifications.notify import (
    notify_dispute_updated,
    notify_payment_received,
)
from logand_backend.domain.payments.currency import from_minor_units
from logand_backend.logging import get_logger

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
_log = get_logger(__name__)

# Stripe's own dispute.status values, collapsed to the four buckets
# db/models/invoices.py's _DISPUTE_STATUS_CHECK allows -- see that
# constant's doc comment for why the "needs_response"/"under_review"
# collapse is fine for what this app currently does differently between
# them (nothing, yet).
_DISPUTE_STATUS_MAP = {
    "warning_needs_response": "needs_response",
    "needs_response": "needs_response",
    "warning_under_review": "under_review",
    "under_review": "under_review",
    "won": "won",
    "lost": "lost",
    "warning_closed": "won",
}


@router.post("/stripe")
async def stripe_webhook(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    # NOTE: no session/CSRF auth here by design -- Stripe signature verification
    # IS the auth for this endpoint (docs/design/04). Do not add require_admin
    # or csrf checks to this route.
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if sig_header is None:
        raise HTTPException(status_code=400, detail="missing stripe-signature header")

    cfg = AppConfig.from_external(argparse.Namespace())
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, cfg.stripe_webhook_secret
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        _log.warning("stripe webhook rejected: bad signature", exc_info=exc)
        raise HTTPException(
            status_code=400, detail="invalid webhook signature"
        ) from exc

    _log.info(
        "stripe webhook received",
        extra={
            "event_type": event["type"],
            # NOT event.get("id") -- event is a stripe.StripeObject, not a
            # plain dict; this SDK version's StripeObject only implements
            # __getitem__/__contains__, not .get() (same real bug already
            # documented above at intent["latest_charge"]).
            "event_id": event["id"] if "id" in event else None,
        },
    )
    if event["type"] in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        await _handle_payment_intent_event(db, event, cfg)
    elif event["type"] in (
        "charge.dispute.created",
        "charge.dispute.updated",
        "charge.dispute.closed",
    ):
        await _handle_dispute_event(db, event, cfg)
    elif event["type"] == "charge.refund.updated":
        await _handle_refund_updated_event(db, event, cfg)

    return {"status": "received"}


async def _handle_payment_intent_event(
    db: AsyncSession, event: dict, cfg: AppConfig
) -> None:
    intent = event["data"]["object"]
    intent_id = intent["id"]
    succeeded = event["type"] == "payment_intent.succeeded"

    # NOTE: webhook delivery is at-least-once -- key idempotency on
    # stripe_payment_intent_id so a replayed event doesn't double-record a
    # payment (docs/design/04). This SELECT-then-INSERT still has a race
    # window on its own: two overlapping deliveries for the SAME intent
    # (Stripe's own retry landing while the first delivery is still being
    # processed) could both see existing=None before either commits, and
    # both try to insert a Payment row for the same intent_id. The
    # migration 0003_payment_idempotency partial unique index on
    # stripe_payment_intent_id is the actual backstop for that: the
    # second INSERT raises IntegrityError, caught below and treated as
    # "someone else already recorded this," not a real error.
    invoice = (
        await db.execute(
            select(Invoice)
            .where(Invoice.stripe_payment_intent_id == intent_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if invoice is None:
        _log.warning(
            "stripe webhook: no invoice matches this payment intent",
            extra={"stripe_payment_intent_id": intent_id},
        )
        return

    existing = (
        await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if not succeeded and existing.status == "succeeded":
            # M1: a late/out-of-order payment_intent.payment_failed for an
            # intent that already has a succeeded Payment must never
            # downgrade it -- Stripe does not guarantee delivery order, so
            # a failed-then-succeeded retry on the same intent can deliver
            # "succeeded" first. Overwriting status here would leave the
            # invoice "paid" with its only Payment row "failed", which
            # also silently drops the money from get_invoice_stats'
            # total_collected/by_payment_method/net_collected (see
            # FINDINGS.md M1). Treat this as a no-op.
            _log.info(
                "stripe webhook: ignoring late payment_failed for an "
                "already-succeeded intent",
                extra={
                    "invoice_id": str(invoice.id),
                    "stripe_payment_intent_id": intent_id,
                },
            )
            return
        existing.status = "succeeded" if succeeded else "failed"
        await db.flush()
        settled_now = succeeded and await settle_invoice_if_paid(db, invoice)
        # L1: notify whenever this delivery observes a succeeded payment
        # on a now-paid invoice, not only when THIS call is what flipped
        # it to paid -- otherwise a crash between a prior delivery's
        # commit and its email send means the customer is never told,
        # since settle_invoice_if_paid is idempotent and returns False on
        # a retry that finds the invoice already paid. Accepting that a
        # genuine duplicate delivery may re-send the email.
        if succeeded and invoice.status == "paid":
            if settled_now:
                _log.info(
                    "invoice marked paid via stripe (retried intent)",
                    extra={
                        "invoice_id": str(invoice.id),
                        "stripe_payment_intent_id": intent_id,
                    },
                )
            # Release the invoice row lock before the email send (M1
            # pattern; see _handle_dispute_event and refunds.py).
            await db.commit()
            await notify_payment_received(db, cfg, invoice, existing.amount)
        return

    try:
        # A SAVEPOINT (nested transaction), not a bare flush -- if the
        # unique-index race above actually fires, we need to roll back
        # just this failed INSERT, not poison the whole request's
        # transaction (which get_db's dependency commits/rolls back as a
        # single unit around this entire handler).
        async with db.begin_nested():
            db.add(
                Payment(
                    invoice_id=invoice.id,
                    stripe_payment_intent_id=intent_id,
                    amount=from_minor_units(intent["amount"], invoice.currency),
                    status="succeeded" if succeeded else "failed",
                    # NOT intent.get(...) -- `intent` is a stripe.StripeObject,
                    # not a plain dict, and this SDK version's StripeObject
                    # doesn't implement .get() (only __getitem__/__contains__),
                    # so intent.get("latest_charge") raised AttributeError on
                    # every single successful webhook delivery that reached
                    # this line -- found by tests/system/test_stripe_webhooks.py
                    # actually exercising this path instead of mocking it away.
                    transaction_id=intent["latest_charge"]
                    if "latest_charge" in intent
                    else None,
                )
            )
            await db.flush()
    except IntegrityError:
        # Another concurrent delivery for this exact intent_id won the
        # race and already inserted its Payment row -- nothing left for
        # THIS delivery to do; the invoice's paid status below was
        # already (or is about to be) set by that other delivery.
        return

    if succeeded:
        await settle_invoice_if_paid(db, invoice)
        _log.info(
            "invoice marked paid via stripe",
            extra={
                "invoice_id": str(invoice.id),
                "stripe_payment_intent_id": intent_id,
            },
        )
        # Release the invoice row lock before the email send (M1 pattern;
        # see _handle_dispute_event and refunds.py).
        await db.commit()
        await notify_payment_received(
            db, cfg, invoice, from_minor_units(intent["amount"], invoice.currency)
        )
        return
    _log.warning(
        "stripe payment_intent failed",
        extra={"invoice_id": str(invoice.id), "stripe_payment_intent_id": intent_id},
    )
    await db.flush()


async def _handle_dispute_event(db: AsyncSession, event: dict, cfg: AppConfig) -> None:
    """A cardholder disputed a charge (chargeback) -- Stripe's dispute
    object is keyed on `charge`, the same charge id this app already
    stores as Payment.transaction_id (see intent["latest_charge"] above),
    not on the PaymentIntent. Purely informational on this app's side:
    Stripe handles the actual funds-withdrawal/representment flow;
    dispute_status here just makes that visible to an admin (invoice
    detail view) and triggers a notification so they know to act (submit
    evidence) before Stripe's own response deadline.
    """
    dispute = event["data"]["object"]
    dispute_id = dispute["id"]
    charge_id = dispute["charge"]
    raw_status = dispute["status"]
    mapped_status = _DISPUTE_STATUS_MAP.get(raw_status)
    if mapped_status is None:
        _log.warning(
            "stripe dispute webhook: unrecognized dispute status",
            extra={"stripe_dispute_id": dispute_id, "status": raw_status},
        )
        return

    payment = (
        await db.execute(
            select(Payment).where(Payment.transaction_id == charge_id).with_for_update()
        )
    ).scalar_one_or_none()
    if payment is None:
        _log.warning(
            "stripe dispute webhook: no payment matches this charge",
            extra={"stripe_dispute_id": dispute_id, "charge": charge_id},
        )
        return

    prior_status = payment.dispute_status
    status_changed = prior_status != mapped_status
    payment.dispute_status = mapped_status
    payment.stripe_dispute_id = dispute_id
    await db.flush()

    invoice = await db.get(Invoice, payment.invoice_id)

    # Release the Payment row lock (and this request's DB connection's
    # hold on it) BEFORE the admin notification fan-out -- see
    # domain/invoices/refunds.py's identical early-commit-before-external-
    # I/O pattern (its own M1 doc comment) and FINDINGS.md M1. Without
    # this, the lock (and a redelivered event's with_for_update above)
    # would be held across N sequential Gmail round-trips, one per admin.
    await db.commit()

    # Notify only on a real status transition -- Stripe webhook delivery
    # is at-least-once, so a redelivered charge.dispute.closed (same
    # mapped_status as what we already recorded) must not re-send the
    # "dispute resolved" email (see FINDINGS.md L1).
    if invoice is not None and status_changed:
        await notify_dispute_updated(db, cfg, invoice, mapped_status)


async def _handle_refund_updated_event(
    db: AsyncSession, event: dict, cfg: AppConfig
) -> None:
    """A refund this app recorded as "pending" (domain/invoices/refunds.py
    -- Stripe doesn't always settle a refund synchronously) has since
    transitioned. Looks up the row and hands off to
    domain/invoices/refunds.py's apply_refund_settlement for the actual
    status flip and any payment/invoice/notification side effects --
    that function is shared with reconcile_pending_paypal_refunds, which
    is PayPal's equivalent of this webhook (PayPal delivers no refund-
    completion webhook this app subscribes to, so it's reconciled by
    polling instead; see that function's own doc comment).
    """
    stripe_refund = event["data"]["object"]
    stripe_refund_id = stripe_refund["id"]
    mapped_status = STRIPE_REFUND_STATUS_MAP.get(stripe_refund["status"])
    if mapped_status is None or mapped_status == "pending":
        return

    refund = (
        await db.execute(
            select(Refund)
            .where(Refund.stripe_refund_id == stripe_refund_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if refund is None:
        _log.warning(
            "stripe refund-updated webhook: no refund matches this id",
            extra={"stripe_refund_id": stripe_refund_id},
        )
        return

    # No "already settled -> no-op" early return here (see FINDINGS.md
    # L1) -- apply_refund_settlement itself now re-sends the
    # notification on a replayed/duplicate delivery that observes an
    # already-succeeded refund, so a crash in a prior delivery's
    # commit->send window is recoverable on redelivery instead of
    # dropping the email forever.
    await apply_refund_settlement(db, cfg, refund, mapped_status)
