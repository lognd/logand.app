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


async def test_list_customers_filters_by_q_case_insensitive_substring(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    alice = await make_user(
        role="customer", password="pw", email="alice.wong@gmail.com"
    )
    bob = await make_user(role="customer", password="pw", email="bob@example.com")
    await login_as(db_client, admin.email, "pw")

    # Substring match anywhere, not just a prefix -- "the gmail customer"
    # is a real way an admin would remember someone.
    resp = await db_client.get("/api/admin/customers?q=GMAIL")
    emails = {row["email"] for row in resp.json()}
    assert alice.email in emails
    assert bob.email not in emails


async def test_list_customers_q_matching_nothing_returns_empty_list(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await make_user(role="customer", password="pw", email="carol@example.com")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/customers?q=zzz-nonexistent")
    assert resp.status_code == 200
    assert resp.json() == []
