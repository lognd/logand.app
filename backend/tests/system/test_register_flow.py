from __future__ import annotations

from httpx import AsyncClient


async def test_register_returns_202_and_does_not_log_in(
    db_client: AsyncClient,
) -> None:
    """docs/design/16: register() no longer creates a session -- a freshly
    registered account is "unverified" and login() refuses it outright.
    """
    resp = await db_client.post(
        "/api/auth/register",
        json={"email": "fresh-signup@example.com", "password": "a-real-password"},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert resp.status_code == 202, resp.text
    assert "__Host-session" not in db_client.cookies

    login_resp = await db_client.post(
        "/api/auth/login",
        json={"email": "fresh-signup@example.com", "password": "a-real-password"},
        headers={"X-Forwarded-For": "203.0.113.20"},
    )
    assert login_resp.status_code == 403
    assert login_resp.json()["detail"]["code"] == "AuthError.EmailNotVerified"


async def test_register_with_duplicate_email_is_409(
    db_client: AsyncClient, make_user
) -> None:
    user = await make_user(role="customer", password="whatever")

    resp = await db_client.post(
        "/api/auth/register",
        json={"email": user.email, "password": "a-different-password"},
        headers={"X-Forwarded-For": "203.0.113.11"},
    )
    assert resp.status_code == 409


async def test_register_with_short_password_is_422(db_client: AsyncClient) -> None:
    resp = await db_client.post(
        "/api/auth/register",
        json={"email": "short-pw@example.com", "password": "short"},
        headers={"X-Forwarded-For": "203.0.113.12"},
    )
    assert resp.status_code == 422


async def test_register_rate_limited_after_repeated_attempts(
    db_client: AsyncClient,
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.13"}

    last_status = None
    last_headers = None
    for i in range(6):
        resp = await db_client.post(
            "/api/auth/register",
            json={"email": f"spam-{i}@example.com", "password": "a-real-password"},
            headers=headers,
        )
        last_status, last_headers = resp.status_code, resp.headers

    # REGISTER threshold mirrors LOGIN's 5/15min -- the 6th rapid attempt
    # should be rate-limited.
    assert last_status == 429
    assert "retry-after" in {k.lower() for k in last_headers.keys()}


async def test_register_is_exempt_from_csrf_check(db_client: AsyncClient) -> None:
    # No X-CSRF-Token header at all -- /api/auth/register must be exempt,
    # same reasoning as /api/auth/login (no session cookie exists yet to
    # carry a CSRF secret to double-submit against).
    resp = await db_client.post(
        "/api/auth/register",
        json={"email": "no-csrf-needed@example.com", "password": "a-real-password"},
        headers={"X-Forwarded-For": "203.0.113.14"},
    )
    assert resp.status_code == 202
