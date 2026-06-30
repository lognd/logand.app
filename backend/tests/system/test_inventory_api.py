from __future__ import annotations

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_create_location_item_move_and_search(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc_a = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "garage-shelf-3"},
        headers=headers,
    )
    assert loc_a.status_code == 200
    loc_b = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "desk-drawer-a"},
        headers=headers,
    )
    assert loc_b.status_code == 200

    locations = await db_client.get("/api/admin/inventory/locations")
    names = {loc["name"] for loc in locations.json()}
    assert {"garage-shelf-3", "desk-drawer-a"} <= names

    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={
            "name": "resistor",
            "location_id": loc_a.json()["id"],
            "quantity": 100,
        },
        headers=headers,
    )
    assert item_resp.status_code == 200
    item_id = item_resp.json()["id"]

    move_resp = await db_client.patch(
        f"/api/admin/inventory/items/{item_id}",
        params={"location_id": loc_b.json()["id"]},
        headers=headers,
    )
    assert move_resp.status_code == 200

    search_resp = await db_client.get(
        "/api/admin/inventory/items", params={"location_id": loc_b.json()["id"]}
    )
    assert search_resp.status_code == 200
    assert any(item["id"] == item_id for item in search_resp.json())


async def test_duplicate_location_name_rejected(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    first = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "duplicate-name"},
        headers=headers,
    )
    assert first.status_code == 200

    second = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "duplicate-name"},
        headers=headers,
    )
    assert second.status_code == 409


async def test_inventory_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/inventory/locations")
    assert resp.status_code == 401
