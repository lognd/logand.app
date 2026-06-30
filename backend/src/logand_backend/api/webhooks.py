from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.base import get_db

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    # NOTE: no session/CSRF auth here by design -- Stripe signature verification
    # IS the auth for this endpoint (docs/design/04). Do not add require_admin
    # or csrf checks to this route.
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if sig_header is None:
        raise HTTPException(status_code=400, detail="missing stripe-signature header")
    raise NotImplementedError(
        "stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET), "
        "then handle payment_intent.succeeded/.payment_failed idempotently "
        "(key on stripe_payment_intent_id -- webhook delivery is at-least-once); "
        "needs db.models.invoices"
    )
