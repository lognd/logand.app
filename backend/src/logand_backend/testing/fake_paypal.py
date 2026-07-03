from __future__ import annotations

import uuid

from fastapi import FastAPI, Request

# A local HTTP double for the slice of PayPal's real REST API this backend
# calls (domain/payments/providers/paypal.py) -- same reasoning as
# testing/fake_stripe.py's own doc comment: the real httpx-based provider
# code runs unmodified against this, just pointed at a different host
# (AppConfig.paypal_api_base), so a system test exercises the real
# request/response wire format instead of mocking the provider module's
# own functions away.
app = FastAPI(title="fake-paypal (test double, not real PayPal)")

_FAKE_ACCESS_TOKEN = "fake-paypal-access-token"
# In-memory only, module-level state for the lifetime of this process --
# enough to let capture_order echo back the actual amount an order was
# created with (a real system test needs that to confirm the invoice
# actually gets marked paid for the right amount), without needing a real
# database just for a test double.
_orders: dict[str, dict] = {}


@app.post("/v1/oauth2/token")
async def oauth_token() -> dict:
    return {
        "access_token": _FAKE_ACCESS_TOKEN,
        "token_type": "Bearer",
        "expires_in": 32000,
    }


@app.post("/v2/checkout/orders")
async def create_order(request: Request) -> dict:
    body = await request.json()
    unit = body["purchase_units"][0]
    order_id = f"FAKE-ORDER-{uuid.uuid4().hex[:12].upper()}"
    _orders[order_id] = {"reference_id": unit["reference_id"], "amount": unit["amount"]}
    return {
        "id": order_id,
        "status": "CREATED",
        "links": [
            {
                "rel": "approve",
                "href": f"https://fake-paypal.test/checkoutnow?token={order_id}",
                "method": "GET",
            }
        ],
    }


@app.post("/v2/checkout/orders/{order_id}/capture")
async def capture_order(order_id: str) -> dict:
    # A real PayPal capture call has no request body -- the captured
    # amount comes from whatever /orders was created with, tracked in
    # _orders above, so a system test can confirm the invoice actually
    # gets marked paid for the right amount rather than a fixed fake one.
    order = _orders.setdefault(
        order_id,
        {
            "reference_id": "unknown",
            "amount": {"currency_code": "USD", "value": "0.00"},
        },
    )
    # Once minted, remember this order's capture_id/status so a repeat
    # capture call (an idempotent retry) and the GET /orders poll below
    # always echo the SAME capture, matching real PayPal -- rather than
    # minting a fresh capture_id every call.
    capture_id = order.get("capture_id") or (
        f"FAKE-CAPTURE-{uuid.uuid4().hex[:12].upper()}"
    )
    # A test can pre-arm the order (via POST /test/orders/{id}/force-status,
    # below) to make THIS capture come back PENDING rather than the
    # default COMPLETED, exercising capture_invoice_paypal_payment's "held
    # for review" branch; the same endpoint can later move an already-
    # captured order to a terminal status to exercise
    # reconcile_pending_paypal_captures's poll.
    status = order.get("force_status", "COMPLETED")
    order["capture_id"] = capture_id
    order["capture_status"] = status
    return {
        "id": order_id,
        "status": "COMPLETED" if status == "COMPLETED" else "PENDING",
        "purchase_units": [
            {
                # Real PayPal echoes reference_id back on the capture
                # response too, not just on create -- domain/payments/
                # providers/paypal.py's capture_order relies on this to
                # let the caller verify a captured order actually belongs
                # to the invoice it's being applied to.
                "reference_id": order["reference_id"],
                "payments": {
                    "captures": [
                        {
                            "id": capture_id,
                            "status": status,
                            "amount": order["amount"],
                        }
                    ]
                },
            }
        ],
    }


@app.get("/v2/checkout/orders/{order_id}")
async def get_order(order_id: str) -> dict:
    # Backs get_order_status (domain/payments/providers/paypal.py), used
    # by reconcile_pending_paypal_captures to poll a PENDING capture until
    # PayPal resolves it. An order never captured, or one this fake server
    # never saw at all, has no captures entry -- same shape as a real
    # VOIDED order -- so _capture_from_order_body's defensive handling
    # (FINDINGS.md M1) can be exercised against a real HTTP response.
    order = _orders.get(order_id)
    if order is None or "capture_id" not in order:
        return {"id": order_id, "status": "CREATED", "purchase_units": [{}]}
    return {
        "id": order_id,
        "status": order["capture_status"],
        "purchase_units": [
            {
                "reference_id": order["reference_id"],
                "payments": {
                    "captures": [
                        {
                            "id": order["capture_id"],
                            "status": order["capture_status"],
                            "amount": order["amount"],
                        }
                    ]
                },
            }
        ],
    }


@app.post("/test/orders/{order_id}/force-status")
async def force_order_status(order_id: str, request: Request) -> dict:
    """Test-only control endpoint (not part of PayPal's real API) letting
    system tests dictate what the NEXT capture (or a subsequent GET
    /orders poll) reports for this order -- e.g. "PENDING" to simulate a
    capture held for review, then "COMPLETED"/"DECLINED" to simulate the
    reconciler's later poll resolving it."""
    body = await request.json()
    order = _orders.setdefault(
        order_id,
        {
            "reference_id": "unknown",
            "amount": {"currency_code": "USD", "value": "0.00"},
        },
    )
    order["force_status"] = body["status"]
    # Also update an already-captured order's polled status, so a test can
    # arm PENDING at capture time and later move it to COMPLETED/DECLINED
    # for the reconciler's GET /orders poll without re-capturing.
    if "capture_id" in order:
        order["capture_status"] = body["status"]
    return {"ok": True}


@app.post("/v2/payments/captures/{capture_id}/refund")
async def refund_capture(capture_id: str) -> dict:
    # Real PayPal accepts an explicit amount body for a partial refund --
    # this double only needs to echo an id and status back, since
    # refund_capture (domain/payments/providers/paypal.py) only reads
    # those two fields off the response.
    refund_id = f"FAKE-REFUND-{uuid.uuid4().hex[:12].upper()}"
    return {"id": refund_id, "status": "COMPLETED"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=12112)
