from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from httpx import AsyncClient

from logand_backend.testing.fake_paypal import app as fake_paypal_app


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


async def _sent_invoice_as_customer(
    db_client: AsyncClient, make_user, login_as, unit_price: str = "42.00"
):
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": unit_price}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    await db_client.post("/api/auth/logout", headers=admin_headers)
    await login_as(db_client, customer.email, "pw")
    return invoice_id, customer


# -- graceful fallback (PayPal not configured, the common/default case) ----


async def test_payment_methods_lists_paypal_unavailable_when_not_configured(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stripe"] is True
    assert body["paypal"] is False


async def test_pay_via_paypal_returns_503_when_not_configured(
    db_client: AsyncClient, make_user, login_as
) -> None:
    invoice_id, _customer = await _sent_invoice_as_customer(
        db_client, make_user, login_as
    )
    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal", headers=_csrf_headers(db_client)
    )
    assert resp.status_code == 503


# -- real hookup, via a real running fake-PayPal HTTP double ---------------


@pytest.fixture(scope="module")
def fake_paypal_server() -> Iterator[str]:
    """Same convention as test_stripe_fake_server.py's fake_stripe_server
    fixture -- a real uvicorn server on a real port in a background
    thread, since domain/payments/providers/paypal.py makes real httpx
    requests that need something actually listening on a socket."""
    config = uvicorn.Config(
        fake_paypal_app, host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "fake_paypal server did not start in time"
    port = server.servers[0].sockets[0].getsockname()[1]

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


def _configure_paypal(monkeypatch: pytest.MonkeyPatch, fake_paypal_server: str) -> None:
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("PAYPAL_API_BASE", fake_paypal_server)


async def test_payment_methods_lists_paypal_available_once_configured(
    db_client: AsyncClient,
    make_user,
    login_as,
    fake_paypal_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_paypal(monkeypatch, fake_paypal_server)
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")
    assert resp.json()["paypal"] is True


async def test_full_paypal_create_and_capture_marks_invoice_paid(
    db_client: AsyncClient,
    make_user,
    login_as,
    fake_paypal_server: str,
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    from sqlalchemy import select

    from logand_backend.db.models.invoices import Invoice

    _configure_paypal(monkeypatch, fake_paypal_server)
    invoice_id, _customer = await _sent_invoice_as_customer(
        db_client, make_user, login_as, unit_price="88.50"
    )
    headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal", headers=headers
    )
    assert create_resp.status_code == 200, create_resp.text
    body = create_resp.json()
    assert body["order_id"].startswith("FAKE-ORDER-")
    assert body["approval_url"] is not None

    capture_resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal/capture",
        json={"order_id": body["order_id"]},
        headers=headers,
    )
    assert capture_resp.status_code == 200, capture_resp.text
    assert capture_resp.json() == {"status": "captured"}

    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert invoice.status == "paid"


async def test_capture_with_bogus_order_id_still_succeeds_against_fake_server(
    db_client: AsyncClient,
    make_user,
    login_as,
    fake_paypal_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fake server doesn't validate that a captured order_id was ever
    # actually created (see fake_paypal.py's capture_order) -- this test
    # documents that as a known simplification of the double, not a
    # real-PayPal behavior being asserted here.
    _configure_paypal(monkeypatch, fake_paypal_server)
    invoice_id, _customer = await _sent_invoice_as_customer(
        db_client, make_user, login_as
    )
    headers = _csrf_headers(db_client)

    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal/capture",
        json={"order_id": "FAKE-ORDER-NEVERCREATED"},
        headers=headers,
    )
    assert resp.status_code == 200


async def test_pay_via_paypal_rejects_non_payable_invoice(
    db_client: AsyncClient,
    make_user,
    login_as,
    fake_paypal_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_paypal(monkeypatch, fake_paypal_server)
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "10.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]  # never sent -- still draft
    await db_client.post("/api/auth/logout", headers=admin_headers)

    await login_as(db_client, customer.email, "pw")
    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal", headers=_csrf_headers(db_client)
    )
    assert resp.status_code == 409


async def test_capture_rejects_non_payable_invoice(
    db_client: AsyncClient,
    make_user,
    login_as,
    fake_paypal_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_paypal(monkeypatch, fake_paypal_server)
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "10.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]  # never sent -- still draft
    await db_client.post("/api/auth/logout", headers=admin_headers)

    await login_as(db_client, customer.email, "pw")
    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal/capture",
        json={"order_id": "FAKE-ORDER-WHATEVER"},
        headers=_csrf_headers(db_client),
    )
    assert resp.status_code == 409


async def test_capture_returns_502_when_paypal_request_fails(
    db_client: AsyncClient,
    make_user,
    login_as,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real client credentials configured, but PAYPAL_API_BASE points at
    # nothing listening -- exercises capture_order's real httpx.HTTPError
    # handling (PaymentProviderError.RequestFailed -> 502), not a mocked
    # error, same "real infra" convention as the rest of this file.
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("PAYPAL_API_BASE", "http://127.0.0.1:1")

    invoice_id, _customer = await _sent_invoice_as_customer(
        db_client, make_user, login_as
    )
    resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay/paypal/capture",
        json={"order_id": "FAKE-ORDER-WHATEVER"},
        headers=_csrf_headers(db_client),
    )
    assert resp.status_code == 502
