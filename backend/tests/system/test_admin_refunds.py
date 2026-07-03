from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from httpx import AsyncClient
from sqlalchemy import select

from logand_backend.db.models.invoices import Invoice, Payment
from logand_backend.testing.fake_paypal import app as fake_paypal_app
from logand_backend.testing.fake_stripe import app as fake_stripe_app

_WEBHOOK_SECRET = "whsec_fake"


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


def _stripe_signature_header(payload: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


@pytest.fixture(scope="module")
def fake_stripe_server() -> Iterator[str]:
    config = uvicorn.Config(
        fake_stripe_app, host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "fake_stripe server did not start in time"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def fake_paypal_server() -> Iterator[str]:
    config = uvicorn.Config(
        fake_paypal_app, host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "fake_paypal server did not start in time"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


async def _admin_and_paid_invoice_via_manual_payment(
    db_client: AsyncClient, make_user, login_as, unit_price: str = "60.00"
) -> tuple[str, str]:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": unit_price}],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(f"/api/admin/invoices/{invoice_id}/send", headers=headers)

    manual_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/manual",
        json={"method": "zelle", "amount": unit_price},
        headers=headers,
    )
    assert manual_resp.status_code == 200, manual_resp.text
    payment_id = manual_resp.json()["id"]
    return invoice_id, payment_id


async def test_admin_refund_of_manual_payment_full(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, payment_id = await _admin_and_paid_invoice_via_manual_payment(
        db_client, make_user, login_as
    )
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/{payment_id}/refund",
        json={"payment_id": payment_id, "reason": "duplicate charge"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    detail_resp = await db_client.get(
        f"/api/admin/invoices/{invoice_id}", headers=headers
    )
    body = detail_resp.json()
    assert body["status"] == "refunded"
    payment = next(p for p in body["payments"] if p["id"] == payment_id)
    assert payment["status"] == "refunded"
    assert len(payment["refunds"]) == 1
    assert payment["refunds"][0]["reason"] == "duplicate charge"


async def test_admin_refund_partial_amount(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, payment_id = await _admin_and_paid_invoice_via_manual_payment(
        db_client, make_user, login_as, unit_price="60.00"
    )
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/{payment_id}/refund",
        json={"payment_id": payment_id, "amount": "20.00"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    detail_resp = await db_client.get(
        f"/api/admin/invoices/{invoice_id}", headers=headers
    )
    body = detail_resp.json()
    assert body["status"] == "paid"
    payment = next(p for p in body["payments"] if p["id"] == payment_id)
    assert payment["status"] == "partially_refunded"


async def test_admin_refund_body_payment_id_mismatch_is_rejected(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, payment_id = await _admin_and_paid_invoice_via_manual_payment(
        db_client, make_user, login_as
    )
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/{payment_id}/refund",
        json={"payment_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_admin_refund_exceeding_balance_is_rejected(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, payment_id = await _admin_and_paid_invoice_via_manual_payment(
        db_client, make_user, login_as, unit_price="60.00"
    )
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/{payment_id}/refund",
        json={"payment_id": payment_id, "amount": "9999.00"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_admin_refund_of_stripe_payment_calls_real_fake_refund_endpoint(
    db_client: AsyncClient,
    make_user,
    login_as,
    fake_stripe_server: str,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """Drives the refund through a real fake-Stripe HTTP server (same
    convention as test_stripe_fake_server.py) rather than mocking
    stripe.Refund.create away, so this actually proves refund_payment's
    Stripe wiring (payment_intent id, amount in cents) sends what the SDK
    -- and by extension real Stripe -- expects.
    """
    monkeypatch.setenv("STRIPE_API_BASE", fake_stripe_server)

    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "42.00"}],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(f"/api/admin/invoices/{invoice_id}/send", headers=headers)

    intent_id = "pi_refund_test"
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.stripe_payment_intent_id = intent_id
    await db_session.commit()

    payload = json.dumps(
        {
            "id": "evt_" + intent_id,
            "object": "event",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {"id": intent_id, "amount": 4200, "latest_charge": "ch_x"}
            },
        }
    ).encode()
    webhook_resp = await db_client.post(
        "/api/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": _stripe_signature_header(payload)},
    )
    assert webhook_resp.status_code == 200

    payment = (
        await db_session.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
        )
    ).scalar_one()
    payment_id = str(payment.id)

    refund_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/{payment_id}/refund",
        json={"payment_id": payment_id},
        headers=headers,
    )
    assert refund_resp.status_code == 200, refund_resp.text

    await db_session.refresh(payment)
    assert payment.status == "refunded"

    detail_resp = await db_client.get(
        f"/api/admin/invoices/{invoice_id}", headers=headers
    )
    refunds = next(p for p in detail_resp.json()["payments"] if p["id"] == payment_id)[
        "refunds"
    ]
    assert len(refunds) == 1
    assert refunds[0]["stripe_refund_id"].startswith("re_fake_")


def _configure_paypal(monkeypatch: pytest.MonkeyPatch, fake_paypal_server: str) -> None:
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("PAYPAL_API_BASE", fake_paypal_server)


async def test_admin_refund_of_paypal_payment_calls_real_fake_refund_endpoint(
    db_client: AsyncClient,
    make_user,
    login_as,
    fake_paypal_server: str,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    _configure_paypal(monkeypatch, fake_paypal_server)

    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "30.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    await db_client.post("/api/auth/logout", headers=admin_headers)

    await login_as(db_client, customer.email, "pw")
    customer_headers = _csrf_headers(db_client)
    order_resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal", headers=customer_headers
    )
    order_id = order_resp.json()["order_id"]
    capture_resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal/capture",
        json={"order_id": order_id},
        headers=customer_headers,
    )
    assert capture_resp.status_code == 200, capture_resp.text
    await db_client.post("/api/auth/logout", headers=customer_headers)

    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)
    payment = (
        await db_session.execute(
            select(Payment).where(Payment.invoice_id == invoice_id)
        )
    ).scalar_one()
    payment_id = str(payment.id)

    refund_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/{payment_id}/refund",
        json={"payment_id": payment_id},
        headers=admin_headers,
    )
    assert refund_resp.status_code == 200, refund_resp.text

    detail_resp = await db_client.get(
        f"/api/admin/invoices/{invoice_id}", headers=admin_headers
    )
    refunds = next(p for p in detail_resp.json()["payments"] if p["id"] == payment_id)[
        "refunds"
    ]
    assert len(refunds) == 1
    assert refunds[0]["paypal_refund_id"].startswith("FAKE-REFUND-")
