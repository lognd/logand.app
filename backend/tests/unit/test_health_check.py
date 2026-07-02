from __future__ import annotations

from logand_backend.app.config import AppConfig
from logand_backend.scripts.health_check import _redact_url, check_dev_defaults


def test_redact_url_strips_credentials_but_keeps_host_and_db() -> None:
    url = "postgresql+asyncpg://logand:supersecret@db.example.com:5432/logand"
    redacted = _redact_url(url)
    assert "supersecret" not in redacted
    assert "logand:" not in redacted  # username also stripped, not just password
    assert "db.example.com:5432" in redacted
    assert redacted.endswith("/logand")


def test_check_dev_defaults_passes_when_every_secret_is_overridden() -> None:
    cfg = AppConfig(
        session_secret="a-real-secret",
        payment_processor_secret="sk_live_real",
        stripe_webhook_secret="whsec_real",
    )
    assert check_dev_defaults(cfg) is True


def test_check_dev_defaults_fails_when_session_secret_is_still_default() -> None:
    cfg = AppConfig(
        session_secret=AppConfig().session_secret,  # the real default value
        payment_processor_secret="sk_live_real",
        stripe_webhook_secret="whsec_real",
    )
    assert check_dev_defaults(cfg) is False


def test_check_dev_defaults_fails_on_a_completely_default_config() -> None:
    assert check_dev_defaults(AppConfig()) is False
