from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def _sent_invoice_as_customer(db_client: AsyncClient, make_user, login_as):
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "50.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    await db_client.post("/api/auth/logout", headers=admin_headers)
    await login_as(db_client, customer.email, "pw")
    return invoice_id, admin, customer


async def test_customer_uploads_proof_and_admin_can_view_it(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, admin, _customer = await _sent_invoice_as_customer(
        db_client, make_user, login_as
    )
    customer_headers = _csrf_headers(db_client)

    upload_resp = await db_client.post(
        f"/api/invoices/{invoice_id}/payment-proof",
        files={"file": ("zelle-screenshot.png", b"fake-png-bytes", "image/png")},
        headers=customer_headers,
    )
    assert upload_resp.status_code == 200, upload_resp.text
    proof_id = upload_resp.json()["id"]

    await db_client.post("/api/auth/logout", headers=customer_headers)
    await login_as(db_client, admin.email, "pw")

    list_resp = await db_client.get(f"/api/admin/invoices/{invoice_id}/payment-proof")
    assert list_resp.status_code == 200
    proofs = list_resp.json()
    assert len(proofs) == 1
    assert proofs[0]["id"] == proof_id
    assert proofs[0]["content_type"] == "image/png"

    file_resp = await db_client.get(
        f"/api/admin/invoices/{invoice_id}/payment-proof/{proof_id}/file"
    )
    assert file_resp.status_code == 200
    assert file_resp.content == b"fake-png-bytes"
    assert file_resp.headers["content-type"] == "image/png"


async def test_upload_payment_proof_rejects_unsupported_content_type(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, _admin, _customer = await _sent_invoice_as_customer(
        db_client, make_user, login_as
    )
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/payment-proof",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 415


async def test_upload_payment_proof_rejects_draft_invoice(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "50.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]
    # Deliberately NOT sent -- still a draft.
    await db_client.post("/api/auth/logout", headers=admin_headers)
    await login_as(db_client, customer.email, "pw")
    customer_headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/payment-proof",
        files={"file": ("proof.png", b"bytes", "image/png")},
        headers=customer_headers,
    )
    assert resp.status_code == 409


async def test_upload_payment_proof_rejects_someone_elses_invoice(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, _admin, _owner = await _sent_invoice_as_customer(
        db_client, make_user, login_as
    )
    # Log out the owning customer, log in as an unrelated one.
    headers = _csrf_headers(db_client)
    await db_client.post("/api/auth/logout", headers=headers)
    other_customer = await make_user(role="customer", password="pw")
    await login_as(db_client, other_customer.email, "pw")
    other_headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/payment-proof",
        files={"file": ("proof.png", b"bytes", "image/png")},
        headers=other_headers,
    )
    # 404, not 403 -- never confirm another customer's invoice exists
    # (docs/design/04), same convention as every other customer route.
    assert resp.status_code == 404


async def test_admin_payment_proof_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get(f"/api/admin/invoices/{uuid4()}/payment-proof")
    assert resp.status_code == 401


async def test_list_payment_proof_for_invoice_with_none_uploaded_is_empty(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, admin, _customer = await _sent_invoice_as_customer(
        db_client, make_user, login_as
    )
    await db_client.post("/api/auth/logout", headers=_csrf_headers(db_client))
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get(f"/api/admin/invoices/{invoice_id}/payment-proof")
    assert resp.status_code == 200
    assert resp.json() == []
