from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import Invoice

# Same convention as test_invoice_payment.py: /pay calls the real Stripe SDK
# by design (card data never touches this server), so this monkeypatches the
# SDK call rather than hitting Stripe's network for every CI run.
_FAKE_INTENT_ID = "pi_journey_fake"
_FAKE_CLIENT_SECRET = "pi_journey_fake_secret"


def _fake_payment_intent_create(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(id=_FAKE_INTENT_ID, client_secret=_FAKE_CLIENT_SECRET)


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_full_customer_journey_register_to_paid_invoice(
    db_client: AsyncClient,
    make_user,
    login_as,
    db_session: AsyncSession,
) -> None:
    """One end-to-end walk through the whole customer lifecycle, chained in
    the order a real visitor would actually hit it -- register, confirm the
    session is live, log out, confirm the session is really gone, log back
    into the SAME account, get sent an invoice, and pay it. Each of these
    steps already has its own focused test elsewhere (test_register_flow.py,
    test_auth_flow.py, test_invoice_payment.py); this test's value is
    specifically in proving the handoffs between steps work when chained on
    one real account, not any single step in isolation.
    """
    email = "journey-customer@example.com"
    password = "a-real-password-123"

    # 1. Register a brand new account.
    register_resp = await db_client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": "203.0.113.90"},
    )
    assert register_resp.status_code == 200, register_resp.text
    assert "__Host-session" in db_client.cookies

    # 2. Registration logs the account in immediately -- confirm the new
    # session is actually live before doing anything else with it.
    me_after_register = await db_client.get("/api/me")
    assert me_after_register.status_code == 200
    customer_id = me_after_register.json()["user_id"]
    assert me_after_register.json()["role"] == "customer"

    # 3. Log out.
    logout_resp = await db_client.post(
        "/api/auth/logout", headers=_csrf_headers(db_client)
    )
    assert logout_resp.status_code == 200

    # 4. Confirm the session is genuinely over -- not just that logout
    # returned 200, but that the same cookie jar can no longer reach an
    # authenticated route.
    me_after_logout = await db_client.get("/api/me")
    assert me_after_logout.status_code == 401

    # 5. Log back into the SAME account (not a fresh one) with the
    # original password -- proves the account/credentials survived the
    # logout rather than only ever being tested against a fresh login.
    await login_as(db_client, email, password)
    me_after_relogin = await db_client.get("/api/me")
    assert me_after_relogin.status_code == 200
    assert me_after_relogin.json()["user_id"] == customer_id

    # 6. Log out again so an admin session can be established on the same
    # shared cookie jar to create and send an invoice to this customer --
    # mirrors test_invoice_payment.py's _create_and_send_invoice helper,
    # inlined here since this test owns the customer_id it needs to target.
    await db_client.post("/api/auth/logout", headers=_csrf_headers(db_client))

    admin = await make_user(role="admin", password="admin-pw")
    await login_as(db_client, admin.email, "admin-pw")
    admin_headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": customer_id},
        json=[{"description": "consulting", "quantity": "2", "unit_price": "150.00"}],
        headers=admin_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    invoice_id = create_resp.json()["id"]

    send_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    assert send_resp.status_code == 200

    await db_client.post("/api/auth/logout", headers=admin_headers)

    # 7. Log the customer back in (again, the SAME account throughout) and
    # pay the invoice that was just sent to them.
    await login_as(db_client, email, password)
    customer_headers = _csrf_headers(db_client)

    invoices_resp = await db_client.get("/api/invoices")
    assert invoices_resp.status_code == 200
    invoice_ids = [inv["id"] for inv in invoices_resp.json()]
    assert invoice_id in invoice_ids

    with patch("stripe.PaymentIntent.create", side_effect=_fake_payment_intent_create) as mock_create:
        pay_resp = await db_client.post(
            f"/api/invoices/{invoice_id}/pay", headers=customer_headers
        )
    assert pay_resp.status_code == 200, pay_resp.text
    assert pay_resp.json() == {"client_secret": _FAKE_CLIENT_SECRET}
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["amount"] == 30000  # 2 * $150.00 in cents

    # 8. Confirm the payment intent actually got persisted against the
    # invoice, not just returned in the response.
    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert invoice.stripe_payment_intent_id == _FAKE_INTENT_ID

    # 9. Log out one last time and confirm the session is over again --
    # the same "session actually ends" check from step 4, now after a
    # full round trip through the rest of the journey.
    await db_client.post("/api/auth/logout", headers=customer_headers)
    final_me = await db_client.get("/api/me")
    assert final_me.status_code == 401


async def test_journey_customer_cannot_pay_before_invoice_is_sent(
    db_client: AsyncClient,
    make_user,
    login_as,
) -> None:
    """A narrower companion to the happy-path journey above: register,
    log in as the admin who creates the invoice but does NOT send it yet,
    and confirm the customer can't jump ahead and pay a draft invoice
    before it's actually been sent to them."""
    email = "journey-early-pay@example.com"
    password = "another-real-password"

    register_resp = await db_client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": "203.0.113.91"},
    )
    assert register_resp.status_code == 200
    customer_id = (await db_client.get("/api/me")).json()["user_id"]
    await db_client.post("/api/auth/logout", headers=_csrf_headers(db_client))

    admin = await make_user(role="admin", password="admin-pw")
    await login_as(db_client, admin.email, "admin-pw")
    admin_headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": customer_id},
        json=[{"description": "widget", "quantity": "1", "unit_price": "10.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]
    # Deliberately no /send call here.
    await db_client.post("/api/auth/logout", headers=admin_headers)

    await login_as(db_client, email, password)
    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay", headers=_csrf_headers(db_client)
    )
    assert resp.status_code == 409
