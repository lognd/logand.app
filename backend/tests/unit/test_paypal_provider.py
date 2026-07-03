from __future__ import annotations

from logand_backend.app.config import AppConfig
from logand_backend.domain.payments.providers import paypal
from logand_backend.errors import PaymentProviderError


def test_is_configured_false_when_neither_credential_set() -> None:
    cfg = AppConfig(paypal_client_id=None, paypal_client_secret=None)
    assert paypal.is_configured(cfg) is False


def test_is_configured_false_when_only_one_credential_set() -> None:
    cfg = AppConfig(paypal_client_id="client-id", paypal_client_secret=None)
    assert paypal.is_configured(cfg) is False


def test_is_configured_true_when_both_credentials_set() -> None:
    cfg = AppConfig(paypal_client_id="client-id", paypal_client_secret="client-secret")
    assert paypal.is_configured(cfg) is True


def test_api_base_defaults_to_sandbox() -> None:
    cfg = AppConfig(paypal_mode="sandbox")
    assert paypal._api_base(cfg) == "https://api-m.sandbox.paypal.com"


def test_api_base_switches_to_live() -> None:
    cfg = AppConfig(paypal_mode="live")
    assert paypal._api_base(cfg) == "https://api-m.paypal.com"


def test_api_base_override_takes_priority_over_mode() -> None:
    cfg = AppConfig(paypal_mode="live", paypal_api_base="http://localhost:12112")
    assert paypal._api_base(cfg) == "http://localhost:12112"


def test_capture_from_order_body_uses_capture_status_not_order_status() -> None:
    # Regression test for M1: PayPal can return order-level status
    # "COMPLETED" while the individual capture is "PENDING" (e.g. held
    # for review). PayPalCapture.status must reflect the capture, since
    # that is what capture_invoice_paypal_payment's payability guard
    # checks -- reading the order status would treat unsettled money as
    # settled.
    body = {
        "id": "FAKE-ORDER-1",
        "status": "COMPLETED",
        "purchase_units": [
            {
                "reference_id": "ref-1",
                "payments": {
                    "captures": [
                        {
                            "id": "FAKE-CAPTURE-1",
                            "status": "PENDING",
                            "amount": {"currency_code": "USD", "value": "10.00"},
                        }
                    ]
                },
            }
        ],
    }

    capture = paypal._capture_from_order_body(body)

    assert capture.status == "PENDING"


def test_capture_from_order_body_returns_none_when_captures_array_is_empty() -> None:
    # Regression test for FINDINGS.md M1: a VOIDED/cancelled order can
    # come back with a purchase_units[0].payments.captures that is present
    # but empty -- _capture_from_order_body must return None (letting
    # _get_order turn that into Err(RequestFailed)) rather than raising an
    # IndexError that would escape get_order_status entirely and abort
    # the whole reconcile_pending_paypal_captures batch.
    body = {
        "id": "FAKE-ORDER-1",
        "status": "VOIDED",
        "purchase_units": [
            {
                "reference_id": "ref-1",
                "payments": {"captures": []},
            }
        ],
    }

    assert paypal._capture_from_order_body(body) is None


def test_capture_from_order_body_returns_none_when_payments_key_missing() -> None:
    # Same regression as above, but for an order that never even got a
    # "payments" key at all (e.g. never captured) -- must not KeyError.
    body = {
        "id": "FAKE-ORDER-1",
        "status": "CREATED",
        "purchase_units": [{"reference_id": "ref-1"}],
    }

    assert paypal._capture_from_order_body(body) is None


def test_capture_from_order_body_returns_none_when_purchase_units_missing() -> None:
    body = {"id": "FAKE-ORDER-1", "status": "VOIDED", "purchase_units": []}

    assert paypal._capture_from_order_body(body) is None


async def test_get_order_status_not_configured_when_credentials_missing() -> None:
    # Mirrors get_refund_status's own NotConfigured guard -- neither
    # function should ever attempt a network call without real
    # credentials set.
    cfg = AppConfig(paypal_client_id=None, paypal_client_secret=None)

    result = await paypal.get_order_status(cfg, "FAKE-ORDER-1")

    assert result.is_err
    assert result.danger_err == PaymentProviderError.NotConfigured
