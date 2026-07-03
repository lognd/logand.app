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


async def test_webhook_retried_intent_settles_invoice_that_failed_then_succeeded(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
    """Regression test for FINDINGS.md H1: a PaymentIntent that first
    fails then succeeds on retry must still settle the invoice -- the
    idempotency "existing payment" branch used to only flip that row's
    status and return, never running the settlement logic, leaving the
    invoice "sent" forever even though the card was actually charged.
    """
    intent_id = "pi_retried"
    invoice_id = await _create_sent_invoice_with_intent(
        db_client, make_user, login_as, intent_id
    )
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.stripe_payment_intent_id = intent_id
    await db_session.commit()

    failed_payload = _payment_intent_event(
        "payment_intent.payment_failed", intent_id, 4200
    )
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=failed_payload,
        headers={"stripe-signature": _stripe_signature_header(failed_payload)},
    )
    assert resp.status_code == 200
    await db_session.refresh(invoice)
    assert invoice.status == "sent"

    succeeded_payload = _payment_intent_event(
        "payment_intent.succeeded", intent_id, 4200
    )
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=succeeded_payload,
        headers={"stripe-signature": _stripe_signature_header(succeeded_payload)},
    )
    assert resp.status_code == 200

    await db_session.refresh(invoice)
    assert invoice.status == "paid"
    assert invoice.paid_at is not None

    payment = (
        await db_session.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one()
    assert payment.status == "succeeded"


def _dispute_event(
    event_type: str, dispute_id: str, charge_id: str, status: str
) -> bytes:
    return json.dumps(
        {
            "id": "evt_" + dispute_id,
            "object": "event",
            "type": event_type,
            "data": {
                "object": {
                    "id": dispute_id,
                    "charge": charge_id,
                    "status": status,
                }
            },
        }
    ).encode()


async def test_dispute_created_event_sets_payment_dispute_status(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
    intent_id = "pi_disputed"
    charge_id = "ch_disputed"
    invoice_id = await _create_sent_invoice_with_intent(
        db_client, make_user, login_as, intent_id
    )
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.stripe_payment_intent_id = intent_id
    await db_session.commit()

    paid_payload = _payment_intent_event(
        "payment_intent.succeeded", intent_id, 4200, latest_charge=charge_id
    )
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=paid_payload,
        headers={"stripe-signature": _stripe_signature_header(paid_payload)},
    )
    assert resp.status_code == 200

    dispute_payload = _dispute_event(
        "charge.dispute.created", "dp_1", charge_id, "needs_response"
    )
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=dispute_payload,
        headers={"stripe-signature": _stripe_signature_header(dispute_payload)},
    )
    assert resp.status_code == 200

    payment = (
        await db_session.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one()
    assert payment.dispute_status == "needs_response"
    assert payment.stripe_dispute_id == "dp_1"

    # Invoice itself is untouched -- disputes are tracked on the payment,
    # not folded into Invoice.status (see api/webhooks.py's
    # _handle_dispute_event doc comment).
    await db_session.refresh(invoice)
    assert invoice.status == "paid"


async def test_dispute_closed_lost_updates_existing_dispute_status(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
    intent_id = "pi_disputed_lost"
    charge_id = "ch_disputed_lost"
    invoice_id = await _create_sent_invoice_with_intent(
        db_client, make_user, login_as, intent_id
    )
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.stripe_payment_intent_id = intent_id
    await db_session.commit()

    paid_payload = _payment_intent_event(
        "payment_intent.succeeded", intent_id, 4200, latest_charge=charge_id
    )
    await db_client.post(
        "/api/webhooks/stripe",
        content=paid_payload,
        headers={"stripe-signature": _stripe_signature_header(paid_payload)},
    )
    created_payload = _dispute_event(
        "charge.dispute.created", "dp_2", charge_id, "needs_response"
    )
    await db_client.post(
        "/api/webhooks/stripe",
        content=created_payload,
        headers={"stripe-signature": _stripe_signature_header(created_payload)},
    )

    closed_payload = _dispute_event("charge.dispute.closed", "dp_2", charge_id, "lost")
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=closed_payload,
        headers={"stripe-signature": _stripe_signature_header(closed_payload)},
    )
    assert resp.status_code == 200

    payment = (
        await db_session.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one()
    assert payment.dispute_status == "lost"


async def test_dispute_event_for_unknown_charge_is_ignored_not_a_500(
    db_client: AsyncClient,
) -> None:
    payload = _dispute_event(
        "charge.dispute.created", "dp_unknown", "ch_unknown", "needs_response"
    )
    resp = await db_client.post(
        "/api/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _stripe_signature_header(payload)},
    )
    assert resp.status_code == 200
