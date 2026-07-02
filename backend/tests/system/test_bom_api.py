from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_bom_full_lifecycle(db_client: AsyncClient, make_user, login_as) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "bom-test-shelf"},
        headers=headers,
    )
    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "resistor", "location_id": loc.json()["id"], "quantity": 500},
        headers=headers,
    )
    item_id = item_resp.json()["id"]

    bom_resp = await db_client.post(
        "/api/admin/boms",
        json={
            "name": "PCB Assembly",
            "labor_hours": "2.0",
            "labor_rate": "25.00",
            "overhead_percent": "15.00",
        },
        headers=headers,
    )
    assert bom_resp.status_code == 200
    bom_id = bom_resp.json()["id"]

    list_resp = await db_client.get("/api/admin/boms")
    assert any(b["id"] == bom_id for b in list_resp.json())

    get_resp = await db_client.get(f"/api/admin/boms/{bom_id}")
    assert get_resp.json()["name"] == "PCB Assembly"

    line_resp = await db_client.post(
        f"/api/admin/boms/{bom_id}/lines",
        json={"item_id": item_id, "quantity_per_unit": 10},
        headers=headers,
    )
    assert line_resp.status_code == 200

    remove_resp = await db_client.request(
        "DELETE", f"/api/admin/boms/{bom_id}/lines/{item_id}", headers=headers
    )
    assert remove_resp.status_code == 200

    delete_resp = await db_client.delete(f"/api/admin/boms/{bom_id}", headers=headers)
    assert delete_resp.status_code == 200

    get_after_delete = await db_client.get(f"/api/admin/boms/{bom_id}")
    assert get_after_delete.status_code == 404


async def test_bom_cost_breakdown_endpoint(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "bom-cost-shelf"},
        headers=headers,
    )
    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "capacitor", "location_id": loc.json()["id"], "quantity": 100},
        headers=headers,
    )
    item_id = item_resp.json()["id"]

    bom_resp = await db_client.post(
        "/api/admin/boms",
        json={"name": "Cost test", "labor_hours": "1", "labor_rate": "20"},
        headers=headers,
    )
    bom_id = bom_resp.json()["id"]
    await db_client.post(
        f"/api/admin/boms/{bom_id}/lines",
        json={"item_id": item_id, "quantity_per_unit": 5},
        headers=headers,
    )

    # No unit_cost set on the item yet -- must surface as a real 422,
    # not silently compute a wrong (zero) material cost.
    cost_resp = await db_client.get(f"/api/admin/boms/{bom_id}/cost")
    assert cost_resp.status_code == 422

    # Setting it via the real endpoint fixes that.
    set_cost_resp = await db_client.patch(
        f"/api/admin/inventory/items/{item_id}/unit-cost",
        params={"unit_cost": "0.75"},
        headers=headers,
    )
    assert set_cost_resp.status_code == 200

    cost_resp = await db_client.get(f"/api/admin/boms/{bom_id}/cost")
    assert cost_resp.status_code == 200
    breakdown = cost_resp.json()
    # Compared as Decimal, not exact string equality -- Decimal
    # arithmetic (the division inside overhead_cost's percent math in
    # particular) can carry extra trailing zeros of precision through
    # into the total even when the overhead itself is exactly zero
    # ("3.7500" vs "3.75"), a real formatting artifact, not a wrong
    # value.
    # 5 * 0.75 = 3.75 material, 1hr * 20/hr = 20.00 labor, no overhead.
    assert Decimal(breakdown["material_cost"]) == Decimal("3.75")
    assert Decimal(breakdown["labor_cost"]) == Decimal("20.00")
    assert Decimal(breakdown["total_cost"]) == Decimal("23.75")


async def test_bom_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/boms")
    assert resp.status_code == 401


async def test_bom_consume_endpoint_deducts_real_stock(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "consume-test-shelf"},
        headers=headers,
    )
    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "screw", "location_id": loc.json()["id"], "quantity": 50},
        headers=headers,
    )
    item_id = item_resp.json()["id"]

    bom_resp = await db_client.post(
        "/api/admin/boms", json={"name": "Bracket"}, headers=headers
    )
    bom_id = bom_resp.json()["id"]
    await db_client.post(
        f"/api/admin/boms/{bom_id}/lines",
        json={"item_id": item_id, "quantity_per_unit": 4},
        headers=headers,
    )

    consume_resp = await db_client.post(
        f"/api/admin/boms/{bom_id}/consume",
        json={"build_quantity": 5, "reason": "built 5 brackets"},
        headers=headers,
    )
    assert consume_resp.status_code == 200
    assert len(consume_resp.json()["adjustment_ids"]) == 1

    search_resp = await db_client.get(
        "/api/admin/inventory/items", params={"q": "screw"}
    )
    # 50 - (4 * 5) = 30
    assert any(i["id"] == item_id and i["quantity"] == 30 for i in search_resp.json())

    history_resp = await db_client.get(
        f"/api/admin/inventory/items/{item_id}/adjustments"
    )
    assert history_resp.json()[0]["reason"] == "built 5 brackets"


async def test_bom_consume_endpoint_rejects_insufficient_stock(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "consume-fail-shelf"},
        headers=headers,
    )
    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "rare-part", "location_id": loc.json()["id"], "quantity": 2},
        headers=headers,
    )
    item_id = item_resp.json()["id"]

    bom_resp = await db_client.post(
        "/api/admin/boms", json={"name": "Needs a lot"}, headers=headers
    )
    bom_id = bom_resp.json()["id"]
    await db_client.post(
        f"/api/admin/boms/{bom_id}/lines",
        json={"item_id": item_id, "quantity_per_unit": 10},
        headers=headers,
    )

    consume_resp = await db_client.post(
        f"/api/admin/boms/{bom_id}/consume",
        json={"build_quantity": 1},
        headers=headers,
    )
    assert consume_resp.status_code == 422
