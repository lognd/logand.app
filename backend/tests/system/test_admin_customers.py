from __future__ import annotations

from httpx import AsyncClient


async def test_list_customers_returns_only_customer_role_accounts(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer_a = await make_user(role="customer", password="pw")
    customer_b = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/customers")
    assert resp.status_code == 200
    emails = {row["email"] for row in resp.json()}
    assert customer_a.email in emails
    assert customer_b.email in emails
    assert admin.email not in emails


async def test_list_customers_returns_ids_usable_for_invoice_creation(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/customers")
    row = next(r for r in resp.json() if r["email"] == customer.email)
    assert row["id"] == str(customer.id)


async def test_list_customers_requires_admin(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/customers")
    assert resp.status_code == 401


async def test_list_customers_response_never_includes_password_hash(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/customers")
    for row in resp.json():
        assert set(row.keys()) == {"id", "email"}
