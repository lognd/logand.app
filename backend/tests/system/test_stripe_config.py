from __future__ import annotations

import pytest
from httpx import AsyncClient

# Same config-visibility pattern as test_zelle_config.py: the
# payment-methods route re-reads AppConfig per request, so a
# monkeypatched env var is enough to flip what it advertises.


async def test_payment_methods_hides_stripe_when_publishable_key_unset(
    db_client: AsyncClient, make_user, login_as, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY", raising=False)
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")

    assert resp.status_code == 200
    body = resp.json()
    # Without the pk_ the browser can't mount Stripe's card form at all,
    # so the card option must be hidden, not offered and left to fail --
    # see get_payment_methods' own comment.
    assert body["stripe"] is False
    assert body["stripe_publishable_key"] is None


async def test_payment_methods_returns_publishable_key_once_configured(
    db_client: AsyncClient, make_user, login_as, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_abc123")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")

    assert resp.status_code == 200
    body = resp.json()
    assert body["stripe"] is True
    assert body["stripe_publishable_key"] == "pk_test_abc123"


async def test_payment_methods_hides_stripe_when_secret_unset(
    db_client: AsyncClient, make_user, login_as, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for M1 in FINDINGS.md: the publishable key alone is
    NOT enough to advertise "stripe": True -- the server also needs a real
    payment_processor_secret to ever mint a PaymentIntent, or the card
    button would dead-end on every /pay call once a customer clicked it."""
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_abc123")
    monkeypatch.delenv("PAYMENT_PROCESSOR_SECRET", raising=False)
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")

    assert resp.status_code == 200
    body = resp.json()
    assert body["stripe"] is False


async def test_pay_invoice_refuses_when_secret_unset(
    db_client: AsyncClient, make_user, login_as, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for M1 in FINDINGS.md: POST /pay must refuse (503),
    not silently mint a PaymentIntent with an unset/placeholder secret --
    same predicate as get_payment_methods, re-checked here since a client
    could hit this route directly regardless of what the GET advertised."""
    monkeypatch.delenv("PAYMENT_PROCESSOR_SECRET", raising=False)
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = {"X-CSRF-Token": db_client.cookies["csrf_token"]}

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "25.00"}],
        headers=headers,
    )
    assert create_resp.status_code == 200
    invoice_id = create_resp.json()["id"]
    send_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert send_resp.status_code == 200
    await db_client.post("/api/auth/logout", headers=headers)

    await login_as(db_client, customer.email, "pw")
    headers = {"X-CSRF-Token": db_client.cookies["csrf_token"]}

    resp = await db_client.post(f"/api/invoices/{invoice_id}/pay", headers=headers)

    assert resp.status_code == 503
