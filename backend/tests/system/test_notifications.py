from __future__ import annotations

import json
import shutil
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.users import User
from logand_backend.testing.fake_smtp import FakeSmtpServer


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


# -- graceful fallback (SMTP not configured, the common/default case) ------


async def test_sending_invoice_does_not_fail_when_smtp_not_configured(
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
    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert resp.status_code == 200


# -- real hookup, via a real running fake-SMTP server -----------------------


async def test_sending_invoice_emails_the_customer(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    _configure_smtp(monkeypatch, fake_smtp_server)
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

    assert len(fake_smtp_server.messages) == 1
    msg = fake_smtp_server.messages[0]
    assert msg["To"] == customer.email
    assert msg.is_multipart()
    content_types = {part.get_content_type() for part in msg.walk()}
    assert "text/plain" in content_types
    assert "text/html" in content_types
    assert msg["List-Unsubscribe"] is not None
    assert msg["List-Unsubscribe"].startswith("<")
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "123 Main St, Springfield" in msg.get_body(("html",)).get_content()


async def test_sending_invoice_attaches_txt_and_for_robots_json_last(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    """The user's explicit request: a plaintext copy and a for-robots.json
    export attached to the invoice-sent email, with the JSON explicitly
    LAST so a human skimming attachments sees the readable copies first.
    The PDF attachment is asserted only when latexmk is actually
    available -- generate_invoice_pdf is best-effort and this test
    otherwise runs in environments without a LaTeX toolchain installed
    (see tests/system/test_invoice_pdf_generation.py's own skip logic).
    """
    _configure_smtp(monkeypatch, fake_smtp_server)
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

    msg = fake_smtp_server.messages[0]
    attachments = list(msg.iter_attachments())
    filenames = [part.get_filename() for part in attachments]

    assert filenames[-1] == "for-robots.json"
    assert f"invoice-{invoice_id}.txt" in filenames

    if shutil.which("latexmk") is not None:
        assert filenames == [
            f"invoice-{invoice_id}.pdf",
            f"invoice-{invoice_id}.txt",
            "for-robots.json",
        ]
        pdf_part = attachments[0]
        assert pdf_part.get_content_type() == "application/pdf"
    else:
        assert filenames == [f"invoice-{invoice_id}.txt", "for-robots.json"]

    txt_part = next(p for p in attachments if p.get_filename().endswith(".txt"))
    assert txt_part.get_content_type() == "text/plain"
    txt_content = txt_part.get_content()
    assert f"Invoice {invoice_id}" in txt_content
    assert "widget" in txt_content

    json_part = next(p for p in attachments if p.get_filename() == "for-robots.json")
    assert json_part.get_content_type() == "application/json"
    payload = json.loads(json_part.get_content())
    assert payload["invoice_id"] == invoice_id
    assert payload["line_items"][0]["description"] == "widget"
    assert payload["line_items"][0]["quantity"] == "1.00"
    assert payload["line_items"][0]["unit_price"] == "10.00"


async def test_manual_payment_emails_the_customer(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    _configure_smtp(monkeypatch, fake_smtp_server)
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
    assert len(fake_smtp_server.messages) == 1  # the invoice-sent email

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/payments/manual",
        json={"method": "zelle", "amount": "75.00"},
        headers=headers,
    )
    assert resp.status_code == 200

    assert len(fake_smtp_server.messages) == 2
    payment_email = fake_smtp_server.messages[1]
    assert payment_email["To"] == customer.email
    assert "75.00" in payment_email.get_body(("plain",)).get_content()


async def test_opted_out_customer_is_not_emailed(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
    db_session: AsyncSession,
) -> None:
    _configure_smtp(monkeypatch, fake_smtp_server)
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

    assert fake_smtp_server.messages == []


# -- unsubscribe endpoint ----------------------------------------------------


async def test_unsubscribe_get_does_not_opt_the_user_out(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
    db_session: AsyncSession,
) -> None:
    """Regression coverage for FINDINGS.md L1: a bare GET (what a
    corporate link-scanner or mail-client link-preview prefetch does)
    must render a confirm page, not mutate `emails_opted_out` -- only the
    POST-back below actually applies the opt-out.
    """
    _configure_smtp(monkeypatch, fake_smtp_server)
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

    msg = fake_smtp_server.messages[0]
    unsubscribe_url = msg["List-Unsubscribe"].strip("<>")
    token = unsubscribe_url.split("token=", 1)[1]

    # No session/CSRF headers at all -- this is the whole point, a
    # logged-out human clicking a link in an email must be able to reach
    # this page without authenticating.
    resp = await db_client.get("/api/unsubscribe", params={"token": token})
    assert resp.status_code == 200
    assert "<form" in resp.text
    assert "Unsubscribe" in resp.text

    # refresh(customer), not a fresh select() -- `customer` is already
    # loaded in db_session's identity map from make_user's own refresh()
    # call, and a plain select() merging a row for an already-loaded PK
    # does NOT overwrite already-loaded attributes by default (it's not a
    # cache-miss the way session.get() might imply) -- refresh() is what
    # actually forces a new read from the DB.
    await db_session.refresh(customer)
    assert customer.emails_opted_out is False

    # The confirm page's own form POSTs back to the same route with the
    # token still in the query string -- that IS what actually applies
    # the opt-out, exercised directly here.
    confirm_resp = await db_client.post("/api/unsubscribe", params={"token": token})
    assert confirm_resp.status_code == 200
    await db_session.refresh(customer)
    assert customer.emails_opted_out is True


async def test_unsubscribe_one_click_post(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
    db_session: AsyncSession,
) -> None:
    _configure_smtp(monkeypatch, fake_smtp_server)
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

    msg = fake_smtp_server.messages[0]
    unsubscribe_url = msg["List-Unsubscribe"].strip("<>")
    token = unsubscribe_url.split("token=", 1)[1]

    resp = await db_client.post("/api/unsubscribe", params={"token": token})
    assert resp.status_code == 200

    await db_session.refresh(customer)
    assert customer.emails_opted_out is True


async def test_unsubscribe_rejects_invalid_token(db_client: AsyncClient) -> None:
    resp = await db_client.get("/api/unsubscribe", params={"token": "garbage"})
    assert resp.status_code == 400
