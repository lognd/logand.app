from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import Invoice, Payment


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_admin_records_manual_payment_and_invoice_becomes_paid(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "75.00"}],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(f"/api/admin/invoices/{invoice_id}/send", headers=headers)

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/manual",
        json={"method": "zelle", "amount": "75.00", "note": "Zelle confirmation #9981"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert invoice.status == "paid"

    get_resp = await db_client.get(f"/api/admin/invoices/{invoice_id}", headers=headers)
    payments = get_resp.json()["payments"]
    assert len(payments) == 1
    assert payments[0]["method"] == "zelle"
    assert payments[0]["note"] == "Zelle confirmation #9981"


async def test_manual_payment_rejects_invalid_method(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "10.00"}],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(f"/api/admin/invoices/{invoice_id}/send", headers=headers)

    # "stripe" is deliberately not an accepted manual method (see
    # domain/invoices/service.py's ManualPaymentMethod doc comment) --
    # only real webhook/API-capture code paths ever create a "stripe" or
    # real-PayPal-capture Payment row.
    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/manual",
        json={"method": "stripe", "amount": "10.00"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_manual_payment_requires_admin(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    other_customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/invoices/{other_customer.id}/payments/manual",
        json={"method": "zelle", "amount": "10.00"},
        headers=headers,
    )
    # 401, not 403 -- require_admin (auth/sessions.py) returns the same
    # SessionNotFound-shaped 401 for "wrong role" as it does for "no
    # session at all," matching this codebase's existing convention.
    assert resp.status_code == 401


async def test_manual_payment_rejects_draft_invoice_over_http(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "10.00"}],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]  # never sent -- still draft

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/manual",
        json={"method": "zelle", "amount": "10.00"},
        headers=headers,
    )
    assert resp.status_code == 409


async def test_partial_manual_payment_keeps_invoice_payable_over_http(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
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

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/manual",
        json={"method": "other", "amount": "30.00"},
        headers=headers,
    )
    assert resp.status_code == 200

    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert invoice.status == "sent"

    # The invoice is still payable -- a customer could still complete it
    # via the real Stripe /pay flow for the remaining balance (this test
    # only confirms the invoice STAYS payable, not the remaining-balance
    # computation on the Stripe side, which is out of scope here).
    payments = (
        (
            await db_session.execute(
                select(Payment).where(Payment.invoice_id == invoice_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(payments) == 1
    assert payments[0].amount == 30
