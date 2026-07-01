from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import Invoice

# /pay calls the REAL Stripe API (stripe.PaymentIntent.create) by design --
# card data never touches this server (see invoices_public.py's NOTE), so
# there's no local fake to swap it for. Tests here monkeypatch the SDK call
# itself rather than hitting Stripe's network for every CI run, which would
# be slow, non-deterministic, and require a real (even if test-mode) API
# key nobody should need just to run the test suite.
_FAKE_INTENT_ID = "pi_fake_created"
_FAKE_CLIENT_SECRET = "pi_fake_created_secret_abc123"


def _fake_payment_intent_create(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(id=_FAKE_INTENT_ID, client_secret=_FAKE_CLIENT_SECRET)


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def _create_and_send_invoice(
    db_client: AsyncClient, make_user, login_as, customer=None
) -> tuple[str, "object"]:
    admin = await make_user(role="admin", password="pw")
    customer = customer or await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "99.00"}],
        headers=headers,
    )
    assert create_resp.status_code == 200
    invoice_id = create_resp.json()["id"]

    send_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert send_resp.status_code == 200

    await db_client.post("/api/auth/logout", headers=headers)
    return invoice_id, customer


@pytest.fixture
def mock_stripe_payment_intent_create():
    with patch(
        "stripe.PaymentIntent.create", side_effect=_fake_payment_intent_create
    ) as m:
        yield m


async def test_pay_invoice_creates_payment_intent(
    db_client: AsyncClient,
    make_user,
    login_as,
    db_session: AsyncSession,
    mock_stripe_payment_intent_create,
) -> None:
    invoice_id, customer = await _create_and_send_invoice(
        db_client, make_user, login_as
    )
    await login_as(db_client, customer.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(f"/api/invoices/{invoice_id}/pay", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"client_secret": _FAKE_CLIENT_SECRET}

    mock_stripe_payment_intent_create.assert_called_once()
    call_kwargs = mock_stripe_payment_intent_create.call_args.kwargs
    assert call_kwargs["amount"] == 9900  # $99.00 in cents
    assert call_kwargs["currency"] == "usd"
    assert call_kwargs["metadata"] == {"invoice_id": invoice_id}

    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert invoice.stripe_payment_intent_id == _FAKE_INTENT_ID


async def test_pay_invoice_rejects_already_paid_invoice(
    db_client: AsyncClient,
    make_user,
    login_as,
    db_session: AsyncSession,
    mock_stripe_payment_intent_create,
) -> None:
    invoice_id, customer = await _create_and_send_invoice(
        db_client, make_user, login_as
    )
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.status = "paid"
    await db_session.commit()

    await login_as(db_client, customer.email, "pw")
    headers = _csrf_headers(db_client)
    resp = await db_client.post(f"/api/invoices/{invoice_id}/pay", headers=headers)
    assert resp.status_code == 409
    mock_stripe_payment_intent_create.assert_not_called()


async def test_pay_invoice_rejects_draft_invoice(
    db_client: AsyncClient,
    make_user,
    login_as,
    mock_stripe_payment_intent_create,
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post("/api/auth/logout", headers=headers)

    await login_as(db_client, customer.email, "pw")
    headers = _csrf_headers(db_client)
    resp = await db_client.post(f"/api/invoices/{invoice_id}/pay", headers=headers)
    assert resp.status_code == 409
    mock_stripe_payment_intent_create.assert_not_called()


async def test_pay_invoice_cannot_pay_another_customers_invoice(
    db_client: AsyncClient,
    make_user,
    login_as,
    mock_stripe_payment_intent_create,
) -> None:
    invoice_id, _owner = await _create_and_send_invoice(db_client, make_user, login_as)
    other = await make_user(role="customer", password="pw")

    await login_as(db_client, other.email, "pw")
    headers = _csrf_headers(db_client)
    resp = await db_client.post(f"/api/invoices/{invoice_id}/pay", headers=headers)
    assert resp.status_code == 404
    mock_stripe_payment_intent_create.assert_not_called()
