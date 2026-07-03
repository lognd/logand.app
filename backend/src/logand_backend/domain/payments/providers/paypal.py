from __future__ import annotations

from decimal import Decimal

import httpx
from pydantic import BaseModel
from typani.result import Err, Ok, Result

from logand_backend.app.config import AppConfig
from logand_backend.errors import PaymentProviderError

# https://api-m.sandbox.paypal.com / https://api-m.paypal.com -- PayPal's
# own naming for its two REST API environments (not "test"/"prod").
_SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
_LIVE_BASE = "https://api-m.paypal.com"


def is_configured(cfg: AppConfig) -> bool:
    """True once real PayPal API credentials are actually set -- every
    caller (the /pay/paypal route, GET /api/payment-methods) checks this
    BEFORE ever calling create_order/capture_order, so the graceful
    "not hooked up yet, use Zelle/in-person instead" path never depends
    on a real network call failing first.
    """
    return bool(cfg.paypal_client_id and cfg.paypal_client_secret)


def _api_base(cfg: AppConfig) -> str:
    if cfg.paypal_api_base:
        return cfg.paypal_api_base
    return _SANDBOX_BASE if cfg.paypal_mode == "sandbox" else _LIVE_BASE


def _pay_page_url(cfg: AppConfig, invoice_id: str) -> str:
    return f"{cfg.public_base_url}/invoices/{invoice_id}/pay"


class PayPalOrder(BaseModel):
    model_config = {"frozen": True}

    order_id: str
    approval_url: str | None


class PayPalCapture(BaseModel):
    model_config = {"frozen": True}

    order_id: str
    status: str
    captured_amount: Decimal
    captured_currency: str
    # PayPal's own echo of the `reference_id` this app set on create_order
    # (the invoice id, as a string) -- the caller MUST verify this matches
    # the invoice it's capturing against before trusting the capture at
    # all, see api/invoices_public.py's capture route. Never assume the
    # client-supplied order_id in the capture request actually belongs to
    # the invoice URL it was posted to.
    reference_id: str | None
    # PayPal refunds are issued against THIS id, not order_id -- see
    # refund_capture below. Stored on Payment.paypal_capture_id so a
    # later refund doesn't need to re-derive it.
    capture_id: str


class PayPalRefund(BaseModel):
    model_config = {"frozen": True}

    refund_id: str
    status: str


async def _get_access_token(
    client: httpx.AsyncClient, cfg: AppConfig
) -> Result[str, PaymentProviderError]:
    # PayPal's OAuth2 client-credentials flow -- a fresh token per call
    # rather than caching one: simpler, and this is a low-volume path (an
    # invoice payment, not a hot loop), so the extra round trip isn't
    # worth the complexity of a cache with its own expiry bugs to get
    # wrong.
    try:
        resp = await client.post(
            f"{_api_base(cfg)}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(cfg.paypal_client_id or "", cfg.paypal_client_secret or ""),
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return Err(PaymentProviderError.RequestFailed)
    return Ok(resp.json()["access_token"])


async def create_order(
    cfg: AppConfig, invoice_id: str, amount: Decimal, currency: str
) -> Result[PayPalOrder, PaymentProviderError]:
    if not is_configured(cfg):
        return Err(PaymentProviderError.NotConfigured)

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_result = await _get_access_token(client, cfg)
        if token_result.is_err:
            return Err(token_result.danger_err)
        token = token_result.danger_ok

        # return_url/cancel_url: PayPal redirects the customer's browser
        # back here after approval, appending "?token=<order_id>" (that
        # param name is PayPal's own, not something this app chose) --
        # the frontend's Pay.tsx watches for that param to know it should
        # call the capture endpoint automatically once the customer is
        # back, rather than needing a separate "confirm payment" click.
        try:
            resp = await client.post(
                f"{_api_base(cfg)}/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [
                        {
                            "reference_id": invoice_id,
                            "amount": {
                                "currency_code": currency.upper(),
                                "value": f"{amount:.2f}",
                            },
                        }
                    ],
                    "application_context": {
                        "return_url": _pay_page_url(cfg, invoice_id),
                        "cancel_url": _pay_page_url(cfg, invoice_id),
                    },
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return Err(PaymentProviderError.RequestFailed)

        body = resp.json()
        approval_url = next(
            (
                link["href"]
                for link in body.get("links", [])
                if link.get("rel") == "approve"
            ),
            None,
        )
        return Ok(PayPalOrder(order_id=body["id"], approval_url=approval_url))


async def capture_order(
    cfg: AppConfig, order_id: str
) -> Result[PayPalCapture, PaymentProviderError]:
    if not is_configured(cfg):
        return Err(PaymentProviderError.NotConfigured)

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_result = await _get_access_token(client, cfg)
        if token_result.is_err:
            return Err(token_result.danger_err)
        token = token_result.danger_ok

        try:
            resp = await client.post(
                f"{_api_base(cfg)}/v2/checkout/orders/{order_id}/capture",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return Err(PaymentProviderError.RequestFailed)

        body = resp.json()
        purchase_unit = body["purchase_units"][0]
        capture = purchase_unit["payments"]["captures"][0]
        return Ok(
            PayPalCapture(
                order_id=body["id"],
                status=body["status"],
                captured_amount=Decimal(capture["amount"]["value"]),
                captured_currency=capture["amount"]["currency_code"],
                reference_id=purchase_unit.get("reference_id"),
                capture_id=capture["id"],
            )
        )


async def refund_capture(
    cfg: AppConfig, capture_id: str, amount: Decimal, currency: str
) -> Result[PayPalRefund, PaymentProviderError]:
    """Refunds (fully or partially) a completed capture -- PayPal's
    Refunds API is keyed on the CAPTURE id, not the order id, unlike
    create_order/capture_order above. Called from
    domain/invoices/refunds.py::refund_payment for any Payment whose
    method is "paypal" and paypal_capture_id is set (i.e. a real Orders
    API payment, not a manually-recorded one -- see Payment.
    paypal_capture_id's own doc comment).
    """
    if not is_configured(cfg):
        return Err(PaymentProviderError.NotConfigured)

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_result = await _get_access_token(client, cfg)
        if token_result.is_err:
            return Err(token_result.danger_err)
        token = token_result.danger_ok

        try:
            resp = await client.post(
                f"{_api_base(cfg)}/v2/payments/captures/{capture_id}/refund",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "amount": {
                        "value": f"{amount:.2f}",
                        "currency_code": currency.upper(),
                    }
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return Err(PaymentProviderError.RequestFailed)

        body = resp.json()
        return Ok(PayPalRefund(refund_id=body["id"], status=body["status"]))
