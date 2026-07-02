from __future__ import annotations

from datetime import date
from uuid import uuid4

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_capture_receipt_with_only_a_photo(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/receipts",
        files={"file": ("receipt.jpg", b"fake-jpeg-bytes", "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    receipt_id = resp.json()["id"]

    list_resp = await db_client.get("/api/admin/receipts")
    receipt = next(r for r in list_resp.json() if r["id"] == receipt_id)
    assert receipt["vendor"] is None
    assert receipt["amount"] is None
    assert receipt["reconciled_budget_entry_id"] is None


async def test_capture_receipt_with_full_metadata(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/receipts",
        params={
            "vendor": "Home Depot",
            "amount": "42.17",
            "category": "supplies",
            "occurred_on": str(date(2026, 6, 1)),
            "note": "lumber",
        },
        files={"file": ("receipt.png", b"fake-png-bytes", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    receipt_id = resp.json()["id"]

    list_resp = await db_client.get("/api/admin/receipts")
    receipt = next(r for r in list_resp.json() if r["id"] == receipt_id)
    assert receipt["vendor"] == "Home Depot"
    assert receipt["amount"] == "42.17"
    assert receipt["category"] == "supplies"
    assert receipt["note"] == "lumber"


async def test_capture_receipt_rejects_unsupported_content_type(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/receipts",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 415


async def test_capture_receipt_rejects_empty_file(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/receipts",
        files={"file": ("receipt.jpg", b"", "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_download_receipt_file_streams_original_bytes(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/receipts",
        files={"file": ("receipt.jpg", b"exact-original-bytes", "image/jpeg")},
        headers=headers,
    )
    receipt_id = resp.json()["id"]

    download_resp = await db_client.get(f"/api/admin/receipts/{receipt_id}/file")
    assert download_resp.status_code == 200
    assert download_resp.content == b"exact-original-bytes"


async def test_download_nonexistent_receipt_file_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get(f"/api/admin/receipts/{uuid4()}/file")
    assert resp.status_code == 404


async def test_reconcile_receipt_against_budget_entry(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    receipt_resp = await db_client.post(
        "/api/admin/receipts",
        files={"file": ("receipt.jpg", b"bytes", "image/jpeg")},
        headers=headers,
    )
    receipt_id = receipt_resp.json()["id"]

    entry_resp = await db_client.post(
        "/api/admin/budget",
        params={
            "amount": "42.17",
            "category": "supplies",
            "occurred_on": str(date(2026, 6, 1)),
        },
        headers=headers,
    )
    entry_id = entry_resp.json()["id"]

    reconcile_resp = await db_client.post(
        f"/api/admin/receipts/{receipt_id}/reconcile",
        params={"budget_entry_id": entry_id},
        headers=headers,
    )
    assert reconcile_resp.status_code == 200

    list_resp = await db_client.get("/api/admin/receipts", params={"reconciled": True})
    ids = {r["id"] for r in list_resp.json()}
    assert receipt_id in ids

    unreconciled_resp = await db_client.get(
        "/api/admin/receipts", params={"reconciled": False}
    )
    ids = {r["id"] for r in unreconciled_resp.json()}
    assert receipt_id not in ids


async def test_reconcile_against_nonexistent_budget_entry_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    receipt_resp = await db_client.post(
        "/api/admin/receipts",
        files={"file": ("receipt.jpg", b"bytes", "image/jpeg")},
        headers=headers,
    )
    receipt_id = receipt_resp.json()["id"]

    resp = await db_client.post(
        f"/api/admin/receipts/{receipt_id}/reconcile",
        params={"budget_entry_id": str(uuid4())},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_reconcile_nonexistent_receipt_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    entry_resp = await db_client.post(
        "/api/admin/budget",
        params={
            "amount": "10.00",
            "category": "misc",
            "occurred_on": str(date(2026, 6, 1)),
        },
        headers=headers,
    )
    entry_id = entry_resp.json()["id"]

    resp = await db_client.post(
        f"/api/admin/receipts/{uuid4()}/reconcile",
        params={"budget_entry_id": entry_id},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_delete_receipt(db_client: AsyncClient, make_user, login_as) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    receipt_resp = await db_client.post(
        "/api/admin/receipts",
        files={"file": ("receipt.jpg", b"bytes", "image/jpeg")},
        headers=headers,
    )
    receipt_id = receipt_resp.json()["id"]

    delete_resp = await db_client.delete(
        f"/api/admin/receipts/{receipt_id}", headers=headers
    )
    assert delete_resp.status_code == 200

    list_resp = await db_client.get("/api/admin/receipts")
    assert all(r["id"] != receipt_id for r in list_resp.json())

    delete_again_resp = await db_client.delete(
        f"/api/admin/receipts/{receipt_id}", headers=headers
    )
    assert delete_again_resp.status_code == 404


async def test_receipts_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/receipts")
    assert resp.status_code == 401
