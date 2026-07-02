from __future__ import annotations

from datetime import date

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_admin_create_and_list_budget_entry(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/budget",
        params={
            "amount": "42.50",
            "category": "supplies",
            "occurred_on": str(date(2026, 1, 1)),
            "vendor": "Acme",
        },
        headers=headers,
    )
    assert create_resp.status_code == 200

    list_resp = await db_client.get(
        "/api/admin/budget", params={"category": "supplies"}
    )
    assert list_resp.status_code == 200
    assert any(e["id"] == create_resp.json()["id"] for e in list_resp.json())


async def test_budget_csv_export_returns_text_csv_with_expected_row(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    await db_client.post(
        "/api/admin/budget",
        params={
            "amount": "13.37",
            "category": "travel",
            "occurred_on": str(date(2026, 2, 2)),
        },
        headers=headers,
    )

    export_resp = await db_client.get("/api/admin/budget/export")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"].startswith("text/csv")
    assert "13.37" in export_resp.text
    assert "travel" in export_resp.text


async def test_budget_list_filters_by_date_range(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/budget",
        params={
            "amount": "5.00",
            "category": "misc",
            "occurred_on": str(date(2026, 3, 3)),
        },
        headers=headers,
    )
    entry_id = create_resp.json()["id"]

    in_range = await db_client.get(
        "/api/admin/budget",
        params={"date_from": "2026-01-01", "date_to": "2026-12-31"},
    )
    assert any(e["id"] == entry_id for e in in_range.json())

    out_of_range = await db_client.get(
        "/api/admin/budget",
        params={"date_from": "2027-01-01", "date_to": "2027-12-31"},
    )
    assert all(e["id"] != entry_id for e in out_of_range.json())


async def test_upload_evidence_for_budget_entry(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/budget",
        params={
            "amount": "9.99",
            "category": "supplies",
            "occurred_on": str(date(2026, 4, 4)),
        },
        headers=headers,
    )
    entry_id = create_resp.json()["id"]

    resp = await db_client.post(
        f"/api/admin/budget/{entry_id}/evidence",
        files={"file": ("receipt.png", b"fake-png-bytes", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_upload_evidence_rejects_unsupported_content_type(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/budget",
        params={
            "amount": "1.00",
            "category": "misc",
            "occurred_on": str(date(2026, 5, 5)),
        },
        headers=headers,
    )
    entry_id = create_resp.json()["id"]

    resp = await db_client.post(
        f"/api/admin/budget/{entry_id}/evidence",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 415


async def test_upload_evidence_for_nonexistent_entry_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    from uuid import uuid4

    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/budget/{uuid4()}/evidence",
        files={"file": ("receipt.png", b"fake-png-bytes", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_budget_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/budget")
    assert resp.status_code == 401
