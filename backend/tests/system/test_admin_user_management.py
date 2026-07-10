from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_get_customer_detail(db_client: AsyncClient, make_user, login_as) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get(f"/api/admin/customers/{customer.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == customer.email
    assert body["disabled_at"] is None
    assert "password_hash" not in body


async def test_customer_detail_reports_active_account_state(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw", verified=True)
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get(f"/api/admin/customers/{customer.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["account_state"] == "active"
    assert body["email_verified_at"] is not None
    assert "password_hash" not in body


async def test_customer_detail_reports_unverified_account_state(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw", verified=False)
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get(f"/api/admin/customers/{customer.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["account_state"] == "unverified"
    assert body["email_verified_at"] is None
    assert "password_hash" not in body


async def test_customer_detail_reports_contact_account_state(
    db_client: AsyncClient, make_user, login_as, db_session
) -> None:
    from logand_backend.domain.auth.service import get_or_create_contact_user

    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    contact = (
        await get_or_create_contact_user(db_session, "invoiced@example.com")
    ).danger_ok
    await db_session.commit()

    resp = await db_client.get(f"/api/admin/customers/{contact.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["account_state"] == "contact"
    assert body["email_verified_at"] is None
    assert "password_hash" not in body


async def test_list_customers_includes_account_state(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw", verified=True)
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/customers", params={"q": customer.email})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["account_state"] == "active"
    assert "password_hash" not in body[0]


async def test_deactivate_then_login_fails_then_reactivate_restores_login(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="customer-pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    deactivate_resp = await db_client.post(
        f"/api/admin/customers/{customer.id}/deactivate", headers=headers
    )
    assert deactivate_resp.status_code == 200

    detail_resp = await db_client.get(f"/api/admin/customers/{customer.id}")
    assert detail_resp.json()["disabled_at"] is not None

    await db_client.post("/api/auth/logout", headers=headers)
    failed_login = await db_client.post(
        "/api/auth/login",
        json={"email": customer.email, "password": "customer-pw"},
    )
    assert failed_login.status_code == 401

    await login_as(db_client, admin.email, "pw")
    reactivate_resp = await db_client.post(
        f"/api/admin/customers/{customer.id}/reactivate",
        headers=_csrf_headers(db_client),
    )
    assert reactivate_resp.status_code == 200
    await db_client.post("/api/auth/logout", headers=_csrf_headers(db_client))

    restored_login = await db_client.post(
        "/api/auth/login",
        json={"email": customer.email, "password": "customer-pw"},
    )
    assert restored_login.status_code == 200


async def test_admin_reset_password_lets_customer_log_in_with_new_password(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="old-password")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/customers/{customer.id}/reset-password",
        json={"new_password": "a-fresh-new-password"},
        headers=headers,
    )
    assert resp.status_code == 200

    await db_client.post("/api/auth/logout", headers=headers)
    old_login = await db_client.post(
        "/api/auth/login",
        json={"email": customer.email, "password": "old-password"},
    )
    assert old_login.status_code == 401

    new_login = await db_client.post(
        "/api/auth/login",
        json={"email": customer.email, "password": "a-fresh-new-password"},
    )
    assert new_login.status_code == 200


async def test_reset_password_rejects_short_password(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/customers/{customer.id}/reset-password",
        json={"new_password": "short"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_deactivate_rejects_admin_target(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    other_admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/customers/{other_admin.id}/deactivate", headers=headers
    )
    assert resp.status_code == 403


async def test_customer_account_management_requires_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get(f"/api/admin/customers/{uuid4()}")
    assert resp.status_code == 401
