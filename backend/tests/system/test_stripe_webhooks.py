from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import Invoice, Payment

# Matches AppConfig's default stripe_webhook_secret ("whsec_fake") -- the
# app under test never sets STRIPE_WEBHOOK_SECRET, so this is what
# api/webhooks.py actually verifies against. Kept as its own constant
# (not imported from AppConfig) so a future change to that default fails
# these tests loudly instead of silently signing against whatever the
# field happens to be.
_WEBHOOK_SECRET = "whsec_fake"


def _stripe_signature_header(payload: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    """Builds a real, valid Stripe webhook signature header -- Stripe's
    signing scheme (docs.stripe.com/webhooks#verify-manually) is pure
    HMAC-SHA256 over "{timestamp}.{payload}", no network call needed to
    produce or verify it. Exercising the REAL stripe.Webhook.construct_event
    codepath (rather than monkeypatching it away) is deliberate: signature
    verification is exactly the auth mechanism for this endpoint (see
    webhooks.py's NOTE), so a test that bypasses it isn't actually testing
    the thing most likely to break.
    """
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def _payment_intent_event(
    event_type: str, intent_id: str, amount_cents: int, latest_charge: str = "ch_fake"
) -> bytes:
    # "object": "event" at the top level is required by stripe-python's own
    # construct_event (it branches on event.object to distinguish the
    # newer "v2.core.event" shape from the classic one used here) --
    # every real Stripe webhook payload includes it; a synthetic payload
    # missing it raised an AttributeError deep inside the SDK rather than
    # the intended 400, which is exactly the kind of gap a hand-rolled
    # fixture is supposed to catch.
    return json.dumps(
        {
            "id": "evt_" + intent_id,
            "object": "event",
            "type": event_type,
            "data": {
                "object": {
                    "id": intent_id,
                    "amount": amount_cents,
                    "latest_charge": latest_charge,
                }
            },
        }
    ).encode()


async def _create_sent_invoice_with_intent(
    db_client: AsyncClient, make_user, login_as, intent_id: str
) -> str:
    """Admin-creates an invoice, sends it, and stamps a fake
    stripe_payment_intent_id directly (bypassing the real /pay endpoint,
    which would hit the actual Stripe API) -- returns the invoice id.
    """
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = {"X-CSRF-Token": db_client.cookies["csrf_token"]}

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "42.00"}],
        headers=headers,
    )
    assert create_resp.status_code == 200
    invoice_id = create_resp.json()["id"]

    send_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert send_resp.status_code == 200

    return invoice_id


async def test_webhook_missing_signature_header_is_rejected(
    db_client: AsyncClient,
) -> None:
    resp = await db_client.post("/api/webhooks/stripe", content=b"{}")
    assert resp.status_code == 400


async def test_webhook_invalid_signature_is_rejected(db_client: AsyncClient) -> None:
    payload = _payment_intent_event("payment_intent.succeeded", "pi_bad", 1000)
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": "t=1,v1=not_a_real_signature"},
    )
    assert resp.status_code == 400


async def test_webhook_succeeded_event_marks_invoice_paid(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
    intent_id = "pi_succeeds"
    invoice_id = await _create_sent_invoice_with_intent(
        db_client, make_user, login_as, intent_id
    )
    # Stamp the intent id the same way pay_invoice() would after a real
    # Stripe PaymentIntent.create call -- done directly against the DB here
    # since /pay itself is covered separately with a mocked Stripe client.
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.stripe_payment_intent_id = intent_id
    await db_session.commit()

    payload = _payment_intent_event("payment_intent.succeeded", intent_id, 4200)
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _stripe_signature_header(payload)},
    )
    assert resp.status_code == 200

    await db_session.refresh(invoice)
    assert invoice.status == "paid"

    payment = (
        await db_session.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one()
    assert payment.status == "succeeded"
    assert payment.amount == Decimal("42.00")
    assert payment.invoice_id == invoice.id


async def test_webhook_failed_event_does_not_mark_invoice_paid(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
    intent_id = "pi_fails"
    invoice_id = await _create_sent_invoice_with_intent(
        db_client, make_user, login_as, intent_id
    )
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.stripe_payment_intent_id = intent_id
    await db_session.commit()

    payload = _payment_intent_event("payment_intent.payment_failed", intent_id, 4200)
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _stripe_signature_header(payload)},
    )
    assert resp.status_code == 200

    await db_session.refresh(invoice)
    assert (
        invoice.status == "sent"
    )  # unchanged -- a failed payment doesn't advance status

    payment = (
        await db_session.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one()
    assert payment.status == "failed"


async def test_webhook_replayed_event_is_idempotent(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
    """Stripe webhook delivery is at-least-once (webhooks.py's NOTE) -- the
    same event can arrive twice. A replay must not create a second Payment
    row for the same PaymentIntent.
    """
    intent_id = "pi_replayed"
    invoice_id = await _create_sent_invoice_with_intent(
        db_client, make_user, login_as, intent_id
    )
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.stripe_payment_intent_id = intent_id
    await db_session.commit()

    payload = _payment_intent_event("payment_intent.succeeded", intent_id, 4200)
    for _ in range(2):
        resp = await db_client.post(
            "/api/webhooks/stripe",
            content=payload,
            headers={"stripe-signature": _stripe_signature_header(payload)},
        )
        assert resp.status_code == 200

    payments = (
        (
            await db_session.execute(
                select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(payments) == 1


async def test_webhook_unknown_intent_is_ignored_not_a_500(
    db_client: AsyncClient,
) -> None:
    """No invoice was ever stamped with this intent id (e.g. a stale/test
    event, or a race where the DB write hasn't landed yet) -- the handler
    must no-op, not 500.
    """
    payload = _payment_intent_event("payment_intent.succeeded", "pi_unknown", 100)
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _stripe_signature_header(payload)},
    )
    assert resp.status_code == 200


async def test_webhook_ignores_unhandled_event_types(db_client: AsyncClient) -> None:
    payload = json.dumps(
        {
            "id": "evt_x",
            "object": "event",
            "type": "customer.created",
            "data": {"object": {"id": "cus_x"}},
        }
    ).encode()
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _stripe_signature_header(payload)},
    )
    assert resp.status_code == 200
