from __future__ import annotations

from httpx import AsyncClient


async def test_login_sets_cookies_and_me_reflects_session(
    db_client: AsyncClient, make_user, login_as
) -> None:
    user = await make_user(role="customer", password="hunter2-but-real")

    await login_as(db_client, user.email, "hunter2-but-real")
    assert "__Host-session" in db_client.cookies

    me = await db_client.get("/api/me")
    assert me.status_code == 200
    body = me.json()
    assert body["user_id"] == str(user.id)
    assert body["role"] == "customer"


async def test_login_with_wrong_password_is_rejected(
    db_client: AsyncClient, make_user
) -> None:
    user = await make_user(role="customer", password="the-real-one")

    resp = await db_client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "wrong"},
        headers={"X-Forwarded-For": "198.51.100.1"},
    )
    assert resp.status_code == 401


async def test_me_without_session_is_401(db_client: AsyncClient) -> None:
    resp = await db_client.get("/api/me")
    assert resp.status_code == 401


async def test_logout_clears_session_and_me_then_401s(
    db_client: AsyncClient, make_user, login_as
) -> None:
    user = await make_user(role="admin", password="pw")
    await login_as(db_client, user.email, "pw")

    csrf_token = db_client.cookies["csrf_token"]
    logout_resp = await db_client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": csrf_token}
    )
    assert logout_resp.status_code == 200

    me = await db_client.get("/api/me")
    assert me.status_code == 401


async def test_state_changing_request_without_csrf_header_is_rejected(
    db_client: AsyncClient, make_user, login_as
) -> None:
    user = await make_user(role="admin", password="pw")
    await login_as(db_client, user.email, "pw")

    # logout is a state-changing (POST) request; omit X-CSRF-Token entirely.
    resp = await db_client.post("/api/auth/logout")
    assert resp.status_code == 403


async def test_state_changing_request_with_mismatched_csrf_header_is_rejected(
    db_client: AsyncClient, make_user, login_as
) -> None:
    user = await make_user(role="admin", password="pw")
    await login_as(db_client, user.email, "pw")

    resp = await db_client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": "not-the-real-token"}
    )
    assert resp.status_code == 403


async def test_state_changing_request_with_stale_csrf_cookie_is_rejected(
    db_client: AsyncClient, make_user, login_as
) -> None:
    """Regression test for L1: app.py's middleware now binds the double-
    submit check to the CURRENT session's own stored csrf_secret, not
    just cookie==header -- a matching cookie/header PAIR that is neither
    of them the real session's csrf_secret (e.g. a stale value left over
    from a previous login) must still be rejected, even though a pure
    double-submit check alone would have accepted it.
    """
    user = await make_user(role="admin", password="pw")
    await login_as(db_client, user.email, "pw")

    forged_pair = {"X-CSRF-Token": "stale-value-not-this-sessions-real-secret"}
    db_client.cookies.set("csrf_token", forged_pair["X-CSRF-Token"])

    resp = await db_client.post("/api/auth/logout", headers=forged_pair)
    assert resp.status_code == 403

    # The real session is still alive -- rejected the forged request, did
    # not accidentally revoke anything.
    me = await db_client.get("/api/me")
    assert me.status_code == 200


async def test_login_rate_limited_after_repeated_attempts(
    db_client: AsyncClient, make_user
) -> None:
    user = await make_user(role="customer", password="correct")
    # NOTE: deliberately does NOT use the login_as fixture's X-Forwarded-For
    # spoofing -- this test wants every attempt to land in the same
    # rate-limit bucket. A fixed, dedicated IP (not the ASGITransport
    # default) keeps this test independent of other tests' bucket state.
    headers = {"X-Forwarded-For": "203.0.113.42"}

    last_status = None
    last_headers = None
    for _ in range(6):
        resp = await db_client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "wrong"},
            headers=headers,
        )
        last_status, last_headers = resp.status_code, resp.headers

    # LOGIN threshold is 5/15min per docs/design/02 -- the 6th rapid
    # attempt should be rate-limited.
    assert last_status == 429
    assert "retry-after" in {k.lower() for k in last_headers.keys()}
