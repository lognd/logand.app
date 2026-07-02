from __future__ import annotations

from datetime import date
from uuid import uuid4

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_create_via_raw_distance_and_list(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/mileage",
        params={
            "vehicle": "Civic",
            "occurred_on": str(date(2026, 6, 1)),
            "distance": "12.4",
            "purpose": "client site visit",
        },
        headers=headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    entry_id = create_resp.json()["id"]

    list_resp = await db_client.get("/api/admin/mileage")
    assert list_resp.status_code == 200
    entry = next(e for e in list_resp.json() if e["id"] == entry_id)
    assert entry["distance"] == "12.4"
    assert entry["vehicle"] == "Civic"
    assert entry["business"] is True
    assert entry["start_odometer"] is None


async def test_create_via_odometer_readings_derives_distance(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/mileage",
        params={
            "vehicle": "Civic",
            "occurred_on": str(date(2026, 6, 2)),
            "start_odometer": "10000.0",
            "end_odometer": "10042.5",
        },
        headers=headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    entry_id = create_resp.json()["id"]

    list_resp = await db_client.get("/api/admin/mileage")
    entry = next(e for e in list_resp.json() if e["id"] == entry_id)
    assert entry["distance"] == "42.5"
    assert entry["start_odometer"] == "10000.0"
    assert entry["end_odometer"] == "10042.5"


async def test_create_without_any_distance_input_returns_422(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/mileage",
        params={"vehicle": "Civic", "occurred_on": str(date(2026, 6, 3))},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_create_with_negative_derived_distance_returns_422(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/mileage",
        params={
            "vehicle": "Civic",
            "occurred_on": str(date(2026, 6, 4)),
            "start_odometer": "100.0",
            "end_odometer": "50.0",  # end before start
        },
        headers=headers,
    )
    assert resp.status_code == 422


async def test_list_filters_by_vehicle_business_and_date(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    business_resp = await db_client.post(
        "/api/admin/mileage",
        params={
            "vehicle": "Civic",
            "occurred_on": str(date(2026, 6, 5)),
            "distance": "5.0",
        },
        headers=headers,
    )
    business_id = business_resp.json()["id"]

    personal_resp = await db_client.post(
        "/api/admin/mileage",
        params={
            "vehicle": "Truck",
            "occurred_on": str(date(2026, 6, 6)),
            "distance": "3.0",
            "business": False,
        },
        headers=headers,
    )
    personal_id = personal_resp.json()["id"]

    by_vehicle = await db_client.get("/api/admin/mileage", params={"vehicle": "Civic"})
    ids = {e["id"] for e in by_vehicle.json()}
    assert business_id in ids
    assert personal_id not in ids

    by_business = await db_client.get("/api/admin/mileage", params={"business": False})
    ids = {e["id"] for e in by_business.json()}
    assert personal_id in ids
    assert business_id not in ids

    by_date = await db_client.get(
        "/api/admin/mileage",
        params={"date_from": "2000-01-01", "date_to": "2000-12-31"},
    )
    ids = {e["id"] for e in by_date.json()}
    assert business_id not in ids
    assert personal_id not in ids


async def test_delete_entry_removes_it_from_list(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/mileage",
        params={
            "vehicle": "Civic",
            "occurred_on": str(date(2026, 6, 7)),
            "distance": "1.0",
        },
        headers=headers,
    )
    entry_id = create_resp.json()["id"]

    delete_resp = await db_client.delete(
        f"/api/admin/mileage/{entry_id}", headers=headers
    )
    assert delete_resp.status_code == 200

    list_resp = await db_client.get("/api/admin/mileage")
    assert all(e["id"] != entry_id for e in list_resp.json())

    delete_again_resp = await db_client.delete(
        f"/api/admin/mileage/{entry_id}", headers=headers
    )
    assert delete_again_resp.status_code == 404


async def test_delete_nonexistent_entry_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.delete(f"/api/admin/mileage/{uuid4()}", headers=headers)
    assert resp.status_code == 404


async def test_mileage_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/mileage")
    assert resp.status_code == 401
