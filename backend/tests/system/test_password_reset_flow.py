from __future__ import annotations

from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from logand_backend.testing.fake_smtp import FakeSmtpServer


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


async def test_reset_request_for_real_account_emails_a_reset_link(
    db_client: AsyncClient,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    _configure_smtp(monkeypatch, fake_smtp_server)
    user = await make_user(role="customer", password="old-password-123")

    resp = await db_client.post(
        "/api/auth/password-reset/request",
        json={"email": user.email},
        headers={"X-Forwarded-For": "198.51.100.10"},
    )
    assert resp.status_code == 200

    assert len(fake_smtp_server.messages) == 1
    msg = fake_smtp_server.messages[0]
    assert msg["To"] == user.email
    body = msg.get_body(("plain",)).get_content()
    assert "reset-password?token=" in body


async def test_reset_request_for_unknown_email_gives_identical_response(
    db_client: AsyncClient,
    make_user,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    """The whole point of this route: an attacker probing emails must not
    be able to tell "this account exists" from "it doesn't" via the
    response body, status code, or (in this test) whether an email was
    actually sent -- only the real recipient (if any) sees a difference.
    """
    _configure_smtp(monkeypatch, fake_smtp_server)
    user = await make_user(role="customer", password="old-password-123")

    known_resp = await db_client.post(
        "/api/auth/password-reset/request",
        json={"email": user.email},
        headers={"X-Forwarded-For": "198.51.100.11"},
    )
    unknown_resp = await db_client.post(
        "/api/auth/password-reset/request",
        json={"email": "nobody-real@example.com"},
        headers={"X-Forwarded-For": "198.51.100.12"},
    )

    assert known_resp.status_code == unknown_resp.status_code == 200
    assert known_resp.json() == unknown_resp.json()
    # Only the real account actually got mail -- the identical HTTP
    # response above is what an external prober sees; this assertion is
    # just confirming the test's own fake-SMTP setup did what it should.
    assert len(fake_smtp_server.messages) == 1


async def test_confirm_with_real_token_changes_password_and_allows_login(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
    fake_smtp_server: FakeSmtpServer,
) -> None:
    _configure_smtp(monkeypatch, fake_smtp_server)
    user = await make_user(role="customer", password="old-password-123")

    await db_client.post(
        "/api/auth/password-reset/request",
        json={"email": user.email},
        headers={"X-Forwarded-For": "198.51.100.13"},
    )
    body = fake_smtp_server.messages[0].get_body(("plain",)).get_content()
    token = body.split("reset-password?token=")[1].split()[0].strip()

    confirm_resp = await db_client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "brand-new-password-456"},
    )
    assert confirm_resp.status_code == 200

    old_login = await db_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "old-password-123"},
        headers={"X-Forwarded-For": "198.51.100.14"},
    )
    assert old_login.status_code == 401

    await login_as(db_client, user.email, "brand-new-password-456")
    me = await db_client.get("/api/me")
    assert me.status_code == 200


async def test_confirm_with_bogus_token_is_rejected(db_client: AsyncClient) -> None:
    resp = await db_client.post(
        "/api/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "new_password": "brand-new-password-456"},
    )
    assert resp.status_code == 400


async def test_confirm_rejects_a_password_shorter_than_eight_characters(
    db_client: AsyncClient, make_user
) -> None:
    user = await make_user(role="customer", password="old-password-123")
    resp = await db_client.post(
        "/api/auth/password-reset/request",
        json={"email": user.email},
        headers={"X-Forwarded-For": "198.51.100.15"},
    )
    assert resp.status_code == 200

    confirm_resp = await db_client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": "irrelevant-since-validation-runs-first",
            "new_password": "short",
        },
    )
    assert confirm_resp.status_code == 422
