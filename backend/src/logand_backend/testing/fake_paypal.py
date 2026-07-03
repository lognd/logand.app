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
    order = _orders.get(
        order_id,
        {
            "reference_id": "unknown",
            "amount": {"currency_code": "USD", "value": "0.00"},
        },
    )
    capture_id = f"FAKE-CAPTURE-{uuid.uuid4().hex[:12].upper()}"
    return {
        "id": order_id,
        "status": "COMPLETED",
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
                            "status": "COMPLETED",
                            "amount": order["amount"],
                        }
                    ]
                },
            }
        ],
    }


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
