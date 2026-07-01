from __future__ import annotations

from logand_backend.app.config import AppConfig
from logand_backend.domain.payments.providers import paypal


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
