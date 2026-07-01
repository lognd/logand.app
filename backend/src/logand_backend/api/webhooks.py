from __future__ import annotations

import argparse

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.base import get_db
from logand_backend.db.models.invoices import Invoice, Payment

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
        await _handle_payment_intent_event(db, event)

    return {"status": "received"}


async def _handle_payment_intent_event(db: AsyncSession, event: dict) -> None:
    intent = event["data"]["object"]
    intent_id = intent["id"]
    succeeded = event["type"] == "payment_intent.succeeded"

    # NOTE: webhook delivery is at-least-once -- key idempotency on
    # stripe_payment_intent_id so a replayed event doesn't double-record a
    # payment (docs/design/04).
    existing = (
        await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = "succeeded" if succeeded else "failed"
        await db.flush()
        return

    invoice = (
        await db.execute(
            select(Invoice).where(Invoice.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        return

    db.add(
        Payment(
            invoice_id=invoice.id,
            stripe_payment_intent_id=intent_id,
            amount=intent["amount"] / 100,
            status="succeeded" if succeeded else "failed",
            # NOT intent.get(...) -- `intent` is a stripe.StripeObject, not
            # a plain dict, and this SDK version's StripeObject doesn't
            # implement .get() (only __getitem__/__contains__), so
            # intent.get("latest_charge") raised AttributeError on every
            # single successful webhook delivery that reached this line --
            # found by tests/system/test_stripe_webhooks.py actually
            # exercising this path instead of mocking it away.
            transaction_id=intent["latest_charge"]
            if "latest_charge" in intent
            else None,
        )
    )
    if succeeded:
        invoice.status = "paid"
    await db.flush()
