from __future__ import annotations

from collections.abc import Iterator

import pytest
from httpx import AsyncClient

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


async def _create_and_send_invoice_by_email(
    db_client: AsyncClient, admin_headers: dict[str, str], email: str
) -> str:
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_email": email},
        json=[{"description": "widget", "quantity": "1", "unit_price": "10.00"}],
        headers=admin_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    invoice_id = create_resp.json()["id"]
    send_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    assert send_resp.status_code == 200, send_resp.text
    return invoice_id


# -- (a) unverified registrant cannot read invoices already linked --------


async def test_unverified_registrant_cannot_read_linked_invoices(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    """The load-bearing invariant (docs/design/16): an invoice being
    linked to an email is never enough to see it -- only a verified
    account can. This registers over the contact row (allowed) but
    deliberately never verifies, then confirms login itself is refused
    (there is no session at all to read invoices with).
    """
    _configure_smtp(monkeypatch, fake_smtp_server)
    admin = await make_user(role="admin", password="admin-pw")
    await login_as(db_client, admin.email, "admin-pw")
    admin_headers = _csrf_headers(db_client)

    email = "victim@example.com"
    await _create_and_send_invoice_by_email(db_client, admin_headers, email)
    await db_client.post("/api/auth/logout", headers=admin_headers)

    register_resp = await db_client.post(
        "/api/auth/register",
        json={"email": email, "password": "attacker-password"},
        headers={"X-Forwarded-For": "203.0.113.201"},
    )
    assert register_resp.status_code == 202

    login_resp = await db_client.post(
        "/api/auth/login",
        json={"email": email, "password": "attacker-password"},
        headers={"X-Forwarded-For": "203.0.113.202"},
    )
    assert login_resp.status_code == 403
    assert login_resp.json()["detail"]["code"] == "AuthError.EmailNotVerified"

    # No session cookie was ever set -- there is no way to reach GET
    # /api/invoices at all as this identity.
    assert "__Host-session" not in db_client.cookies


# -- (b) registering over an unverified row is allowed and re-mints -------


async def test_registering_over_unverified_row_reissues_verify_link(
    db_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    _configure_smtp(monkeypatch, fake_smtp_server)
    email = "squatted@example.com"

    first = await db_client.post(
        "/api/auth/register",
        json={"email": email, "password": "first-password"},
        headers={"X-Forwarded-For": "203.0.113.210"},
    )
    assert first.status_code == 202

    second = await db_client.post(
        "/api/auth/register",
        json={"email": email, "password": "second-password"},
        headers={"X-Forwarded-For": "203.0.113.211"},
    )
    assert second.status_code == 202

    # The SECOND password is now the live one -- overwritten, not refused.
    message = fake_smtp_server.messages[-1]
    body = message.get_body(("plain",)).get_content()
    token = body.split("verify-email?token=")[1].split()[0].strip()
    verify_resp = await db_client.post("/api/auth/verify-email", json={"token": token})
    assert verify_resp.status_code == 204

    login_resp = await db_client.post(
        "/api/auth/login",
        json={"email": email, "password": "second-password"},
        headers={"X-Forwarded-For": "203.0.113.212"},
    )
    assert login_resp.status_code == 200

    old_password_login = await db_client.post(
        "/api/auth/login",
        json={"email": email, "password": "first-password"},
        headers={"X-Forwarded-For": "203.0.113.213"},
    )
    assert old_password_login.status_code == 401


# -- (c) registering over an active row is refused -------------------------


async def test_registering_over_active_row_is_refused(
    db_client: AsyncClient, make_user
) -> None:
    user = await make_user(role="customer", password="whatever")

    resp = await db_client.post(
        "/api/auth/register",
        json={"email": user.email, "password": "a-different-password"},
        headers={"X-Forwarded-For": "203.0.113.220"},
    )
    assert resp.status_code == 409


# -- (d) a claim link sets password+verified, then invoices are visible ---


async def test_claim_link_sets_password_and_makes_invoices_visible(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    _configure_smtp(monkeypatch, fake_smtp_server)
    admin = await make_user(role="admin", password="admin-pw")
    await login_as(db_client, admin.email, "admin-pw")
    admin_headers = _csrf_headers(db_client)

    email = "real-customer@example.com"
    invoice_id = await _create_and_send_invoice_by_email(
        db_client, admin_headers, email
    )
    await db_client.post("/api/auth/logout", headers=admin_headers)

    message = fake_smtp_server.messages[-1]
    assert message["To"] == email
    body = message.get_body(("plain",)).get_content()
    claim_token = body.split("claim?token=")[1].split()[0].strip()

    preview_resp = await db_client.get("/api/auth/claim", params={"token": claim_token})
    assert preview_resp.status_code == 200, preview_resp.text
    preview = preview_resp.json()
    assert preview["email"] == email
    assert invoice_id in [inv["id"] for inv in preview["invoices"]]

    confirm_resp = await db_client.post(
        "/api/auth/claim",
        json={"token": claim_token, "password": "claimed-password-123"},
    )
    assert confirm_resp.status_code == 204

    # The SAME token cannot be redeemed twice.
    replay_resp = await db_client.post(
        "/api/auth/claim",
        json={"token": claim_token, "password": "another-password-456"},
    )
    assert replay_resp.status_code == 400

    await login_as(db_client, email, "claimed-password-123")
    invoices_resp = await db_client.get("/api/invoices")
    assert invoices_resp.status_code == 200
    assert invoice_id in [inv["id"] for inv in invoices_resp.json()]


# -- (e) login refused for contact rows and unverified rows ----------------


async def test_login_refused_for_contact_row(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="admin-pw")
    await login_as(db_client, admin.email, "admin-pw")
    admin_headers = _csrf_headers(db_client)

    email = "no-account-yet@example.com"
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_email": email},
        json=[{"description": "widget", "quantity": "1", "unit_price": "10.00"}],
        headers=admin_headers,
    )
    assert create_resp.status_code == 200, create_resp.text

    login_resp = await db_client.post(
        "/api/auth/login",
        json={"email": email, "password": "anything"},
        headers={"X-Forwarded-For": "203.0.113.230"},
    )
    assert login_resp.status_code == 401
    assert login_resp.json()["detail"]["code"] == "AuthError.InvalidCredentials"


async def test_login_refused_for_unverified_row(
    db_client: AsyncClient, make_user
) -> None:
    user = await make_user(
        role="customer", password="the-real-password", verified=False
    )

    login_resp = await db_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "the-real-password"},
        headers={"X-Forwarded-For": "203.0.113.231"},
    )
    assert login_resp.status_code == 403
    assert login_resp.json()["detail"]["code"] == "AuthError.EmailNotVerified"


# -- (f) an existing (backfilled) user can still log in ---------------------


async def test_backfilled_active_user_can_still_log_in(
    db_client: AsyncClient, make_user, login_as
) -> None:
    """make_user() defaults to verified=True (docs/design/16), mirroring
    migration 0022's backfill of every pre-existing row -- this is the
    single most important regression to guard: skipping that backfill
    would lock every existing customer (and the seeded admin) out.
    """
    user = await make_user(role="customer", password="the-real-password")

    await login_as(db_client, user.email, "the-real-password")
    me = await db_client.get("/api/me")
    assert me.status_code == 200
