from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import Invoice, Payment

# Same convention as test_invoice_payment.py -- /pay calls the real Stripe
# SDK, so this monkeypatches the SDK call rather than hitting Stripe's
# network. What THIS test file adds beyond test_invoice_payment.py is
# actually firing requests concurrently (asyncio.gather), not one at a
# time, to prove the row-locking/idempotent-reuse added in this same
# change actually closes the race window rather than just looking correct
# when read sequentially.
_FAKE_INTENT_ID = "pi_concurrency_fake"
_FAKE_CLIENT_SECRET = "pi_concurrency_fake_secret"


def _fake_payment_intent_create(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=_FAKE_INTENT_ID,
        client_secret=_FAKE_CLIENT_SECRET,
        status="requires_payment_method",
        amount=kwargs.get("amount", 6000),
    )


def _fake_payment_intent_retrieve(intent_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=intent_id,
        client_secret=_FAKE_CLIENT_SECRET,
        status="requires_payment_method",
        amount=6000,
    )


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_double_clicked_pay_never_creates_two_live_stripe_intents(
    db_client: AsyncClient,
    make_user,
    login_as,
    db_session: AsyncSession,
) -> None:
    """Simulates a double-clicked "Pay" button (or two open tabs) --
    fires two /pay requests at the same real invoice CONCURRENTLY, not
    one after the other. Without the row lock + idempotent-reuse check in
    api/invoices_public.py::pay_invoice, both requests could pass the
    "invoice.stripe_payment_intent_id is not set yet" read before either
    commits, each create its own live PaymentIntent, and a customer could
    go on to confirm both -- a real double charge. With the fix, exactly
    one PaymentIntent.create call should happen; the second request
    reuses the first's client_secret instead.
    """
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "60.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    await db_client.post("/api/auth/logout", headers=admin_headers)

    await login_as(db_client, customer.email, "pw")
    customer_headers = _csrf_headers(db_client)

    with (
        patch(
            "stripe.PaymentIntent.create", side_effect=_fake_payment_intent_create
        ) as mock_create,
        patch(
            "stripe.PaymentIntent.retrieve", side_effect=_fake_payment_intent_retrieve
        ),
    ):
        resp_a, resp_b = await asyncio.gather(
            db_client.post(f"/api/invoices/{invoice_id}/pay", headers=customer_headers),
            db_client.post(f"/api/invoices/{invoice_id}/pay", headers=customer_headers),
        )

    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text
    # Both responses carry the SAME client_secret -- a customer with two
    # tabs open ends up confirming the same intent no matter which tab
    # they finish in, not two competing ones.
    assert resp_a.json() == resp_b.json() == {"client_secret": _FAKE_CLIENT_SECRET}

    # The real assertion: PaymentIntent.create was only ever called ONCE,
    # no matter how the two concurrent requests interleaved.
    assert mock_create.call_count == 1

    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert invoice.stripe_payment_intent_id == _FAKE_INTENT_ID


async def test_concurrent_partial_manual_payments_still_mark_invoice_paid(
    db_client: AsyncClient,
    make_user,
    login_as,
    db_session: AsyncSession,
) -> None:
    """Two admins (or one admin, two tabs) recording two payments that
    TOGETHER cover the invoice, fired concurrently rather than
    sequentially. Without the row lock in
    domain/invoices/service.py::record_manual_payment, both requests
    could read "existing payments don't cover the total yet" before
    either commits its own new Payment row, and neither would flip the
    invoice to "paid" even though the two amounts together do cover it
    (a lost update) -- confirmed fixed if the invoice ends up "paid" and
    both Payment rows exist.
    """
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "100.00"}],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(f"/api/admin/invoices/{invoice_id}/send", headers=headers)

    resp_a, resp_b = await asyncio.gather(
        db_client.post(
            f"/api/admin/invoices/{invoice_id}/payments/manual",
            json={"method": "zelle", "amount": "50.00"},
            headers=headers,
        ),
        db_client.post(
            f"/api/admin/invoices/{invoice_id}/payments/manual",
            json={"method": "other", "amount": "50.00"},
            headers=headers,
        ),
    )
    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text

    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert invoice.status == "paid"

    rows = (
        (
            await db_session.execute(
                select(Payment).where(Payment.invoice_id == invoice_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert sum(r.amount for r in rows) == 100
