from __future__ import annotations

from uuid import uuid4

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


async def test_move_and_update_quantity_of_nonexistent_item_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "nowhere"},
        headers=headers,
    )

    move_resp = await db_client.patch(
        f"/api/admin/inventory/items/{uuid4()}",
        params={"location_id": loc.json()["id"]},
        headers=headers,
    )
    assert move_resp.status_code == 404

    qty_resp = await db_client.patch(
        f"/api/admin/inventory/items/{uuid4()}",
        params={"quantity": 5},
        headers=headers,
    )
    assert qty_resp.status_code == 404


async def test_update_item_quantity_and_delete(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "the-only-shelf"},
        headers=headers,
    )
    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "widget", "location_id": loc.json()["id"], "quantity": 1},
        headers=headers,
    )
    item_id = item_resp.json()["id"]

    qty_resp = await db_client.patch(
        f"/api/admin/inventory/items/{item_id}",
        params={"quantity": 42},
        headers=headers,
    )
    assert qty_resp.status_code == 200

    search_resp = await db_client.get(
        "/api/admin/inventory/items", params={"q": "widget"}
    )
    assert any(i["id"] == item_id and i["quantity"] == 42 for i in search_resp.json())

    delete_resp = await db_client.delete(
        f"/api/admin/inventory/items/{item_id}", headers=headers
    )
    assert delete_resp.status_code == 200

    delete_again_resp = await db_client.delete(
        f"/api/admin/inventory/items/{item_id}", headers=headers
    )
    assert delete_again_resp.status_code == 404


async def test_inventory_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/inventory/locations")
    assert resp.status_code == 401


async def test_adjust_quantity_and_view_audit_history(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "adjust-test-shelf"},
        headers=headers,
    )
    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "widget", "location_id": loc.json()["id"], "quantity": 10},
        headers=headers,
    )
    item_id = item_resp.json()["id"]

    adjust_resp = await db_client.post(
        f"/api/admin/inventory/items/{item_id}/adjust",
        json={"delta": -3, "reason": "sold at market"},
        headers=headers,
    )
    assert adjust_resp.status_code == 200

    search_resp = await db_client.get(
        "/api/admin/inventory/items", params={"q": "widget"}
    )
    assert any(
        i["id"] == item_id and i["quantity"] == 7 for i in search_resp.json()
    )

    history_resp = await db_client.get(
        f"/api/admin/inventory/items/{item_id}/adjustments"
    )
    assert history_resp.status_code == 200
    rows = history_resp.json()
    assert len(rows) == 1
    assert rows[0]["delta"] == -3
    assert rows[0]["quantity_before"] == 10
    assert rows[0]["quantity_after"] == 7
    assert rows[0]["reason"] == "sold at market"
    assert rows[0]["adjusted_by"] == str(admin.id)


async def test_adjust_quantity_rejects_going_negative(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "adjust-negative-shelf"},
        headers=headers,
    )
    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "widget", "location_id": loc.json()["id"], "quantity": 2},
        headers=headers,
    )
    item_id = item_resp.json()["id"]

    resp = await db_client.post(
        f"/api/admin/inventory/items/{item_id}/adjust",
        json={"delta": -10, "reason": "too many"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_adjust_quantity_requires_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    # A real CSRF header, so this genuinely tests the role check -- not
    # just failing earlier at the CSRF gate (a customer's own valid
    # session still has a valid CSRF cookie; role gating happens after).
    resp = await db_client.post(
        f"/api/admin/inventory/items/{uuid4()}/adjust",
        json={"delta": 1, "reason": "x"},
        headers=_csrf_headers(db_client),
    )
    assert resp.status_code == 401
