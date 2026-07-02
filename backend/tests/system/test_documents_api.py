from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_upload_cad_document_and_list(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/documents",
        params={"title": "Bracket v3", "category": "cad", "tags": ["bracket", "v3"]},
        files={"file": ("bracket.stl", b"fake-stl-bytes", "application/sla")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["id"]

    list_resp = await db_client.get("/api/admin/documents")
    doc = next(d for d in list_resp.json() if d["id"] == doc_id)
    assert doc["title"] == "Bracket v3"
    assert doc["category"] == "cad"
    assert set(doc["tags"]) == {"bracket", "v3"}


async def test_upload_document_linked_to_inventory_item(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    loc_resp = await db_client.post(
        "/api/admin/inventory/locations",
        params={"name": "workshop"},
        headers=headers,
    )
    item_resp = await db_client.post(
        "/api/admin/inventory/items",
        params={"name": "widget", "location_id": loc_resp.json()["id"]},
        headers=headers,
    )
    item_id = item_resp.json()["id"]

    doc_resp = await db_client.post(
        "/api/admin/documents",
        params={
            "title": "Widget manual",
            "category": "manual",
            "inventory_item_id": item_id,
        },
        files={"file": ("manual.pdf", b"fake-pdf-bytes", "application/pdf")},
        headers=headers,
    )
    assert doc_resp.status_code == 200, doc_resp.text
    doc_id = doc_resp.json()["id"]

    list_resp = await db_client.get(
        "/api/admin/documents", params={"inventory_item_id": item_id}
    )
    ids = {d["id"] for d in list_resp.json()}
    assert doc_id in ids


async def test_upload_document_with_nonexistent_inventory_item_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/documents",
        params={
            "title": "Orphan",
            "category": "manual",
            "inventory_item_id": str(uuid4()),
        },
        files={"file": ("manual.pdf", b"bytes", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_upload_document_rejects_unsupported_content_type(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/documents",
        params={"title": "x", "category": "other"},
        files={"file": ("x.exe", b"bytes", "application/x-msdownload")},
        headers=headers,
    )
    assert resp.status_code == 415


async def test_upload_document_rejects_invalid_category(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/documents",
        params={"title": "x", "category": "not-a-real-category"},
        files={"file": ("x.pdf", b"bytes", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_download_document_file_streams_original_bytes(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/documents",
        params={"title": "x", "category": "documentation"},
        files={"file": ("x.pdf", b"exact-original-bytes", "application/pdf")},
        headers=headers,
    )
    doc_id = resp.json()["id"]

    download_resp = await db_client.get(f"/api/admin/documents/{doc_id}/file")
    assert download_resp.status_code == 200
    assert download_resp.content == b"exact-original-bytes"


async def test_download_nonexistent_document_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get(f"/api/admin/documents/{uuid4()}/file")
    assert resp.status_code == 404


async def test_list_filters_by_tag_and_category(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    cad_resp = await db_client.post(
        "/api/admin/documents",
        params={"title": "CAD file", "category": "cad", "tags": ["urgent"]},
        files={"file": ("x.step", b"bytes", "model/step")},
        headers=headers,
    )
    cad_id = cad_resp.json()["id"]

    manual_resp = await db_client.post(
        "/api/admin/documents",
        params={"title": "Manual", "category": "manual"},
        files={"file": ("x.pdf", b"bytes", "application/pdf")},
        headers=headers,
    )
    manual_id = manual_resp.json()["id"]

    by_category = await db_client.get(
        "/api/admin/documents", params={"category": "cad"}
    )
    ids = {d["id"] for d in by_category.json()}
    assert cad_id in ids
    assert manual_id not in ids

    by_tag = await db_client.get("/api/admin/documents", params={"tag": "urgent"})
    ids = {d["id"] for d in by_tag.json()}
    assert cad_id in ids
    assert manual_id not in ids


async def test_delete_document(db_client: AsyncClient, make_user, login_as) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        "/api/admin/documents",
        params={"title": "x", "category": "other"},
        files={"file": ("x.pdf", b"bytes", "application/pdf")},
        headers=headers,
    )
    doc_id = resp.json()["id"]

    delete_resp = await db_client.delete(
        f"/api/admin/documents/{doc_id}", headers=headers
    )
    assert delete_resp.status_code == 200

    list_resp = await db_client.get("/api/admin/documents")
    assert all(d["id"] != doc_id for d in list_resp.json())

    delete_again_resp = await db_client.delete(
        f"/api/admin/documents/{doc_id}", headers=headers
    )
    assert delete_again_resp.status_code == 404


async def test_documents_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/documents")
    assert resp.status_code == 401
