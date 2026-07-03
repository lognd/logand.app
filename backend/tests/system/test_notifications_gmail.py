from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.users import User
from logand_backend.testing import fake_gmail
from logand_backend.testing.fake_gmail import app as fake_gmail_app
from logand_backend.testing.fake_gmail_key import fake_service_account_json

# Same real-running-server convention as test_paypal_flow.py's
# fake_paypal_server -- domain/notifications/mailer.py's Gmail OAuth2 path
# makes real httpx requests (a token exchange, then a send call) that need
# something actually listening on a socket, not an ASGI-transport mock.


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


@pytest.fixture(scope="module")
def fake_gmail_server() -> Iterator[str]:
    config = uvicorn.Config(
        fake_gmail_app, host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "fake_gmail server did not start in time"
    port = server.servers[0].sockets[0].getsockname()[1]

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _reset_fake_gmail() -> Iterator[None]:
    fake_gmail.reset()
    yield
    fake_gmail.reset()


def _configure_gmail_oauth(
    monkeypatch: pytest.MonkeyPatch, server: str, sender: str = "billing@example.com"
) -> None:
    monkeypatch.setenv("GMAIL_SERVICE_ACCOUNT_JSON", fake_service_account_json())
    monkeypatch.setenv("GMAIL_SENDER_EMAIL", sender)
    monkeypatch.setenv("GMAIL_TOKEN_API_BASE", server)
    monkeypatch.setenv("GMAIL_API_BASE", server)
    monkeypatch.setenv("MAILING_ADDRESS", "123 Main St, Springfield")
    # Deliberately NOT setting SMTP_HOST -- proves Gmail OAuth2 alone is
    # sufficient for is_configured()/send_email() to actually send,
    # without plain SMTP also being configured.


# -- real hookup, via a real running fake-Gmail HTTP double ------------------


async def test_sending_invoice_emails_the_customer_via_gmail_oauth(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_gmail_server: str,
) -> None:
    _configure_gmail_oauth(monkeypatch, fake_gmail_server)
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
    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert resp.status_code == 200

    sent = fake_gmail.sent_messages()
    assert len(sent) == 1
    msg = sent[0]
    assert msg["To"] == customer.email
    assert msg["From"] == "billing@example.com"
    assert msg.is_multipart()
    content_types = {part.get_content_type() for part in msg.walk()}
    assert "text/plain" in content_types
    assert "text/html" in content_types
    assert msg["List-Unsubscribe"] is not None
    assert msg["List-Unsubscribe"].startswith("<")
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "123 Main St, Springfield" in msg.get_body(("html",)).get_content()


async def test_manual_payment_emails_the_customer_via_gmail_oauth(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_gmail_server: str,
) -> None:
    _configure_gmail_oauth(monkeypatch, fake_gmail_server)
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
    assert len(fake_gmail.sent_messages()) == 1  # the invoice-sent email

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/manual",
        json={"method": "zelle", "amount": "75.00"},
        headers=headers,
    )
    assert resp.status_code == 200

    sent = fake_gmail.sent_messages()
    assert len(sent) == 2
    payment_email = sent[1]
    assert payment_email["To"] == customer.email
    assert "75.00" in payment_email.get_body(("plain",)).get_content()


async def test_opted_out_customer_is_not_emailed_via_gmail_oauth(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_gmail_server: str,
    db_session: AsyncSession,
) -> None:
    _configure_gmail_oauth(monkeypatch, fake_gmail_server)
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")

    customer_row = (
        await db_session.execute(select(User).where(User.id == customer.id))
    ).scalar_one()
    customer_row.emails_opted_out = True
    await db_session.commit()

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

    assert fake_gmail.sent_messages() == []


async def test_gmail_oauth_takes_precedence_when_smtp_also_configured(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_gmail_server: str,
) -> None:
    """Regression coverage for mailer.py's own documented precedence:
    Gmail OAuth2 wins if both transports are somehow configured at once.
    Points SMTP_HOST at a deliberately unreachable address -- if SMTP
    were used instead, this send would fail/hang, not succeed.
    """
    _configure_gmail_oauth(monkeypatch, fake_gmail_server)
    monkeypatch.setenv("SMTP_HOST", "203.0.113.1")  # TEST-NET-3, unroutable
    monkeypatch.setenv("SMTP_PORT", "587")

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
    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert resp.status_code == 200
    assert len(fake_gmail.sent_messages()) == 1
