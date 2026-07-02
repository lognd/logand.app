from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def _seed_item(db_client: AsyncClient, headers: dict[str, str]) -> str:
    """No dedicated inventory-seed fixture exists for system tests, so
    create through the real, already-tested inventory API -- proves the
    admin data browser sees real rows the same way any other admin
    surface writes them, not just rows inserted via the ORM directly."""
    loc_resp = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "Shelf A"},
        headers=headers,
    )
    assert loc_resp.status_code == 200, loc_resp.text
    location_id = loc_resp.json()["id"]

    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "widget", "location_id": location_id, "quantity": 10},
        headers=headers,
    )
    assert item_resp.status_code == 200, item_resp.text
    return item_resp.json()["id"]


async def test_list_tables_excludes_sessions(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/data/tables")

    assert resp.status_code == 200
    tables = resp.json()
    assert "sessions" not in tables
    assert "inventory_items" in tables


async def test_data_browser_requires_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/data/tables")
    assert resp.status_code == 401


async def test_get_row_never_leaks_password_hash(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get(f"/api/admin/data/tables/users/rows/{customer.id}")

    assert resp.status_code == 200
    assert resp.json()["password_hash"] == "<redacted>"


async def test_update_then_list_changes_then_revert_round_trip(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)
    item_id = await _seed_item(db_client, headers)

    update_resp = await db_client.patch(
        f"/api/admin/data/tables/inventory_items/rows/{item_id}",
        json={"changes": {"quantity": 999}},
        headers=headers,
    )
    assert update_resp.status_code == 200
    change_id = update_resp.json()["change_id"]

    row_resp = await db_client.get(
        f"/api/admin/data/tables/inventory_items/rows/{item_id}"
    )
    assert row_resp.json()["quantity"] == 999

    changes_resp = await db_client.get("/api/admin/data/changes")
    assert changes_resp.status_code == 200
    entry = next(c for c in changes_resp.json() if c["id"] == change_id)
    assert entry["before_state"]["quantity"] == 10
    assert entry["after_state"]["quantity"] == 999

    revert_resp = await db_client.post(
        f"/api/admin/data/changes/{change_id}/revert", headers=headers
    )
    assert revert_resp.status_code == 200

    reverted_row = await db_client.get(
        f"/api/admin/data/tables/inventory_items/rows/{item_id}"
    )
    assert reverted_row.json()["quantity"] == 10


async def test_update_row_rejects_password_hash_column(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.patch(
        f"/api/admin/data/tables/users/rows/{customer.id}",
        json={"changes": {"password_hash": "not-a-real-hash"}},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_delete_row_unknown_id_is_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.delete(
        f"/api/admin/data/tables/inventory_items/rows/{uuid4()}", headers=headers
    )
    assert resp.status_code == 404


async def test_unknown_table_is_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/data/tables/not_a_real_table/rows")
    assert resp.status_code == 404


async def test_sessions_table_is_not_browsable(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/data/tables/sessions/rows")
    assert resp.status_code == 404
