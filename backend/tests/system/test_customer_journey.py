from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import Invoice
from logand_backend.testing.fake_smtp import FakeSmtpServer

# Same convention as test_invoice_payment.py: /pay calls the real Stripe SDK
# by design (card data never touches this server), so this monkeypatches the
# SDK call rather than hitting Stripe's network for every CI run.
_FAKE_INTENT_ID = "pi_journey_fake"
_FAKE_CLIENT_SECRET = "pi_journey_fake_secret"


def _fake_payment_intent_create(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(id=_FAKE_INTENT_ID, client_secret=_FAKE_CLIENT_SECRET)


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


@pytest.fixture
def fake_smtp_server() -> Iterator[FakeSmtpServer]:
    server = FakeSmtpServer()
    server.start()
    yield server
    server.stop()


def _configure_smtp(monkeypatch: pytest.MonkeyPatch, server: FakeSmtpServer) -> None:
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(server.port))
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    monkeypatch.setenv("MAILING_ADDRESS", "123 Main St, Springfield")


async def _register_and_verify(
    db_client: AsyncClient,
    fake_smtp_server: FakeSmtpServer,
    *,
    email: str,
    password: str,
    forwarded_for: str,
) -> None:
    """docs/design/17: register() no longer logs the account in -- it
    mints a 'verify' token and mails it. Walks that whole round trip
    (register -> pull the link out of the fake SMTP inbox -> POST
    /verify-email) so this test's account ends up genuinely "active"
    before anything below tries to log in as it.
    """
    register_resp = await db_client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": forwarded_for},
    )
    assert register_resp.status_code == 202, register_resp.text
    assert "__Host-session" not in db_client.cookies

    message = fake_smtp_server.messages[-1]
    assert message["To"] == email
    body = message.get_body(("plain",)).get_content()
    token = body.split("verify-email?token=")[1].split()[0].strip()

    verify_resp = await db_client.post("/api/auth/verify-email", json={"token": token})
    assert verify_resp.status_code == 204, verify_resp.text


async def test_full_customer_journey_register_to_paid_invoice(
    db_client: AsyncClient,
    make_user,
    login_as,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    """One end-to-end walk through the whole customer lifecycle, chained in
    the order a real visitor would actually hit it -- register, verify the
    email, log in, log out, confirm the session is really gone, log back
    into the SAME account, get sent an invoice, and pay it. Each of these
    steps already has its own focused test elsewhere (test_register_flow.py,
    test_auth_flow.py, test_invoice_payment.py); this test's value is
    specifically in proving the handoffs between steps work when chained on
    one real account, not any single step in isolation.
    """
    _configure_smtp(monkeypatch, fake_smtp_server)
    email = "journey-customer@example.com"
    password = "a-real-password-123"

    # 1. Register a brand new account and verify it (docs/design/17: an
    # unverified account can't log in at all, so this is now a
    # prerequisite step, not an assertion made after the fact).
    await _register_and_verify(
        db_client,
        fake_smtp_server,
        email=email,
        password=password,
        forwarded_for="203.0.113.90",
    )

    # 2. Log in for the first time now that the account is verified.
    await login_as(db_client, email, password)
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

    with patch(
        "stripe.PaymentIntent.create", side_effect=_fake_payment_intent_create
    ) as mock_create:
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
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    """A narrower companion to the happy-path journey above: register,
    log in as the admin who creates the invoice but does NOT send it yet,
    and confirm the customer can't jump ahead and pay a draft invoice
    before it's actually been sent to them."""
    _configure_smtp(monkeypatch, fake_smtp_server)
    email = "journey-early-pay@example.com"
    password = "another-real-password"

    await _register_and_verify(
        db_client,
        fake_smtp_server,
        email=email,
        password=password,
        forwarded_for="203.0.113.91",
    )
    await login_as(db_client, email, password)
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
