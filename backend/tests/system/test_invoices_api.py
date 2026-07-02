from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def test_admin_invoice_create_send_void_lifecycle(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id), "memo": "hello"},
        json=[{"description": "widget", "quantity": "2", "unit_price": "10.00"}],
        headers=headers,
    )
    assert create_resp.status_code == 200
    invoice_id = create_resp.json()["id"]

    detail = await db_client.get(f"/api/admin/invoices/{invoice_id}")
    assert detail.status_code == 200
    assert detail.json()["amount_total"] == "20.00"
    assert detail.json()["status"] == "draft"

    send_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert send_resp.status_code == 200

    void_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/void", headers=headers
    )
    assert void_resp.status_code == 200

    detail = await db_client.get(f"/api/admin/invoices/{invoice_id}")
    assert detail.json()["status"] == "void"


async def test_admin_invoice_list_filters_by_status(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]

    draft_only = await db_client.get("/api/admin/invoices", params={"status": "draft"})
    assert any(inv["id"] == invoice_id for inv in draft_only.json())

    sent_only = await db_client.get("/api/admin/invoices", params={"status": "sent"})
    assert all(inv["id"] != invoice_id for inv in sent_only.json())


async def test_admin_invoice_list_filters_by_customer_and_date(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    other_customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]

    by_customer = await db_client.get(
        "/api/admin/invoices", params={"customer_id": str(customer.id)}
    )
    assert any(inv["id"] == invoice_id for inv in by_customer.json())

    by_other_customer = await db_client.get(
        "/api/admin/invoices", params={"customer_id": str(other_customer.id)}
    )
    assert all(inv["id"] != invoice_id for inv in by_other_customer.json())

    by_date = await db_client.get(
        "/api/admin/invoices",
        params={"date_from": "2000-01-01", "date_to": "2999-01-01"},
    )
    assert isinstance(by_date.json(), list)


async def test_send_nonexistent_invoice_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/invoices/{uuid4()}/send", headers=headers
    )
    assert resp.status_code == 404


async def test_send_already_sent_invoice_returns_409(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(f"/api/admin/invoices/{invoice_id}/send", headers=headers)

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert resp.status_code == 409


async def test_void_nonexistent_invoice_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/admin/invoices/{uuid4()}/void", headers=headers
    )
    assert resp.status_code == 404


async def test_void_draft_invoice_returns_409(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]  # still draft, never sent

    resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/void", headers=headers
    )
    assert resp.status_code == 409


async def test_admin_get_nonexistent_invoice_returns_404(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get(f"/api/admin/invoices/{uuid4()}")
    assert resp.status_code == 404


async def test_customer_cannot_see_another_customers_invoice(
    db_client: AsyncClient, make_user, login_as
) -> None:
    """Explicit invariant from docs/design/04: ownership-isolation failures
    must be 404, never 403 -- the response must not confirm the invoice
    exists at all to a customer who doesn't own it."""
    admin = await make_user(role="admin", password="pw")
    owner = await make_user(role="customer", password="pw")
    other = await make_user(role="customer", password="pw")

    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(owner.id)},
        json=[],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post("/api/auth/logout", headers=headers)

    await login_as(db_client, other.email, "pw")
    resp = await db_client.get(f"/api/invoices/{invoice_id}")
    assert resp.status_code == 404


async def test_customer_sees_own_invoice(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")

    await login_as(db_client, admin.email, "pw")
    headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[],
        headers=headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post("/api/auth/logout", headers=headers)

    await login_as(db_client, customer.email, "pw")
    resp = await db_client.get(f"/api/invoices/{invoice_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == invoice_id


async def test_admin_routes_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/invoices")
    assert resp.status_code == 401
