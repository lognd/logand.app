from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from httpx import AsyncClient

from logand_backend.testing.fake_stripe import app as fake_stripe_app


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


@pytest.fixture(scope="module")
def fake_stripe_server() -> Iterator[str]:
    """Runs testing/fake_stripe.py as a REAL server on a REAL port in a
    background thread, for the one test below that needs an actual TCP
    endpoint -- stripe-python makes real HTTP requests via its own client,
    not through anything ASGITransport (or any other in-process shortcut)
    can intercept, so exercising the real request/response wire format
    genuinely requires something listening on a real socket.

    Session/module-scoped (not per-test) since starting a real uvicorn
    server has real (if small) startup cost -- there's nothing test-
    specific about the server itself, only about what each test sends it.
    """
    config = uvicorn.Config(
        fake_stripe_app, host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # uvicorn picks an OS-assigned free port only once its socket is
    # actually bound -- poll briefly rather than guessing a fixed port
    # that could collide with something else already listening.
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "fake_stripe server did not start in time"
    port = server.servers[0].sockets[0].getsockname()[1]

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


async def test_pay_invoice_against_real_fake_stripe_http_server(
    db_client: AsyncClient,
    make_user,
    login_as,
    fake_stripe_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unlike test_invoice_payment.py's mock_stripe_payment_intent_create
    (which replaces stripe.PaymentIntent.create itself via
    unittest.mock.patch), this test never touches stripe-python's own
    code -- it points AppConfig.stripe_api_base at a REAL running HTTP
    server (see the fixture above) and lets the real SDK make a real
    request over a real socket. That's what actually proves the
    STRIPE_API_BASE config wiring in api/invoices_public.py works end to
    end, which a patched-function test can't -- a patch would stay green
    even if that wiring were silently deleted.
    """
    monkeypatch.setenv("STRIPE_API_BASE", fake_stripe_server)

    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "25.00"}],
        headers=admin_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    invoice_id = create_resp.json()["id"]
    send_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    assert send_resp.status_code == 200
    await db_client.post("/api/auth/logout", headers=admin_headers)

    await login_as(db_client, customer.email, "pw")
    customer_headers = _csrf_headers(db_client)

    pay_resp = await db_client.post(
        f"/api/invoices/{invoice_id}/pay", headers=customer_headers
    )
    assert pay_resp.status_code == 200, pay_resp.text
    body = pay_resp.json()
    assert "client_secret" in body
    # The fake server's client_secret is always "{intent_id}_secret_...",
    # not a hardcoded constant -- confirming the prefix matches proves this
    # really did round-trip through the fake server's own response, not a
    # coincidentally-similar value from somewhere else.
    assert body["client_secret"].startswith("pi_fake_")


def test_fake_stripe_server_shape_matches_what_stripe_python_expects() -> None:
    """A narrower unit-level sanity check on the double itself: feed it a
    SimpleNamespace-style request-equivalent form body directly (bypassing
    an actual HTTP round trip) and confirm the response has every field
    stripe-python's PaymentIntent object construction actually reads.
    Cheap and fast; the system test above is what proves the real
    request/response wire format works end to end.
    """
    import asyncio

    from starlette.datastructures import FormData
    from starlette.requests import Request

    async def _run() -> dict:
        form = FormData(
            [("amount", "5000"), ("currency", "usd"), ("metadata[invoice_id]", "xyz")]
        )

        async def receive() -> dict:
            return {"type": "http.disconnect"}

        request = Request(scope={"type": "http", "headers": []}, receive=receive)
        request._form = form  # type: ignore[attr-defined]

        from logand_backend.testing.fake_stripe import create_payment_intent

        return await create_payment_intent(request)

    result = asyncio.run(_run())
    for field in (
        "id",
        "object",
        "amount",
        "currency",
        "metadata",
        "status",
        "client_secret",
    ):
        assert field in result
    assert result["amount"] == 5000
    assert result["metadata"] == {"invoice_id": "xyz"}
    assert result["object"] == "payment_intent"
