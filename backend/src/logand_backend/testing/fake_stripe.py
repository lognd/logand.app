from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request

# A local HTTP double for the tiny slice of Stripe's real API this backend
# actually calls (stripe.PaymentIntent.create -- see api/invoices_public.py)
# -- NOT a mock of the stripe-python SDK itself. Pointing stripe.api_base at
# this (see AppConfig.stripe_api_base) means the real stripe-python client
# still runs its real request-building/serialization/response-parsing code,
# it just talks to this process instead of api.stripe.com. That's a
# meaningfully different (and stronger) guarantee than the
# unittest.mock.patch("stripe.PaymentIntent.create", ...) convention used
# elsewhere in this test suite (test_invoice_payment.py,
# test_customer_journey.py): those patches replace stripe-python's own code
# entirely, so they'd stay green even if a stripe-python upgrade changed
# what that call actually sends over the wire. Driving it through a real
# HTTP round trip against this double is what makes it possible to test the
# integration itself, not just this backend's own use of the SDK.
#
# Deliberately NOT trying to reimplement Stripe's real behavior/validation
# (declining specific test card numbers, 3DS flows, etc.) -- this exists
# purely so a system test can exercise "POST amount+currency+metadata,
# get back a real-shaped PaymentIntent with a client_secret" without a
# live Stripe account, not to be a full Stripe simulator.
app = FastAPI(title="fake-stripe (test double, not real Stripe)")


@app.post("/v1/payment_intents")
async def create_payment_intent(request: Request) -> dict:
    # stripe-python sends this as application/x-www-form-urlencoded (the
    # same wire format the real Stripe API expects), including nested
    # dicts (metadata) as repeated bracketed keys, e.g.
    # "metadata[invoice_id]=...". Parsing that generically here (rather
    # than assuming only the fields this app currently sends) keeps this
    # double honest about the real Stripe request format instead of
    # special-casing exactly one caller's shape.
    form = await request.form()
    metadata: dict[str, str] = {}
    amount = 0
    currency = "usd"
    for key, value in form.multi_items():
        # Every field this fake Stripe endpoint cares about is a plain
        # text field (amount/currency/metadata[...]) -- an UploadFile
        # would only ever appear for a real file-upload field, which
        # nothing here sends. Skipping it (rather than str(value), which
        # would stringify the UploadFile object itself into garbage) is
        # what actually satisfies the type checker's real UploadFile |
        # str union correctly.
        if not isinstance(value, str):
            continue
        if key == "amount":
            amount = int(value)
        elif key == "currency":
            currency = value
        elif key.startswith("metadata[") and key.endswith("]"):
            metadata[key[len("metadata[") : -1]] = value

    intent_id = f"pi_fake_{uuid.uuid4().hex[:24]}"
    return {
        "id": intent_id,
        "object": "payment_intent",
        "amount": amount,
        "currency": currency,
        "metadata": metadata,
        "status": "requires_payment_method",
        "client_secret": f"{intent_id}_secret_{uuid.uuid4().hex[:16]}",
        "livemode": False,
        "created": int(time.time()),
    }


if __name__ == "__main__":
    import uvicorn

    # Standalone entrypoint: `uv run python -m logand_backend.testing.fake_stripe`
    # -- used by docker-compose.test.yml's fake-stripe service and by
    # anyone running the full stack locally without a real Stripe account.
    uvicorn.run(app, host="0.0.0.0", port=12111)
