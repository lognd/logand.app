from __future__ import annotations

import argparse
from decimal import Decimal

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.base import get_db
from logand_backend.db.models.invoices import Invoice, Payment
from logand_backend.domain.notifications.notify import notify_payment_received

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


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
        raise HTTPException(
            status_code=400, detail="invalid webhook signature"
        ) from exc

    if event["type"] in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        await _handle_payment_intent_event(db, event, cfg)

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
        return

    existing = (
        await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = "succeeded" if succeeded else "failed"
        await db.flush()
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
                    amount=intent["amount"] / 100,
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
        invoice.status = "paid"
        await db.flush()
        await notify_payment_received(
            db, cfg, invoice, Decimal(str(intent["amount"] / 100))
        )
        return
    await db.flush()
