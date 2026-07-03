from __future__ import annotations

import base64
import json
import uuid

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from logand_backend.app.config import AppConfig
from logand_backend.domain.notifications import mailer
from logand_backend.testing.fake_gmail_key import fake_service_account_info

# Pure-logic unit tests, no network -- the full HTTP round trip (token
# exchange + Gmail API send against a real running fake-gmail server) is
# covered by tests/system/test_notifications_gmail.py instead, same split
# as test_notify.py (unit, mocked) vs test_notifications.py (system, a
# real fake-SMTP server).


def _cfg(**overrides: object) -> AppConfig:
    return AppConfig(**overrides)  # type: ignore[arg-type]


# -- is_configured / _gmail_oauth_configured --------------------------------


def test_is_configured_false_when_nothing_set() -> None:
    assert mailer.is_configured(_cfg()) is False


def test_is_configured_true_with_smtp_only() -> None:
    assert mailer.is_configured(_cfg(smtp_host="smtp.example.com")) is True


def test_is_configured_true_with_gmail_oauth_only() -> None:
    cfg = _cfg(
        gmail_service_account_json=json.dumps(fake_service_account_info()),
        gmail_sender_email="billing@example.com",
    )
    assert mailer.is_configured(cfg) is True


def test_is_configured_true_with_both() -> None:
    cfg = _cfg(
        smtp_host="smtp.example.com",
        gmail_service_account_json=json.dumps(fake_service_account_info()),
        gmail_sender_email="billing@example.com",
    )
    assert mailer.is_configured(cfg) is True


def test_gmail_oauth_configured_requires_both_fields_together() -> None:
    assert (
        mailer._gmail_oauth_configured(
            _cfg(gmail_service_account_json=json.dumps(fake_service_account_info()))
        )
        is False
    )
    assert (
        mailer._gmail_oauth_configured(_cfg(gmail_sender_email="billing@example.com"))
        is False
    )
    assert (
        mailer._gmail_oauth_configured(
            _cfg(
                gmail_service_account_json=json.dumps(fake_service_account_info()),
                gmail_sender_email="billing@example.com",
            )
        )
        is True
    )


# -- build_message: From header depends on the active transport -------------


def test_build_message_uses_smtp_from_address_in_smtp_mode() -> None:
    cfg = _cfg(smtp_host="smtp.example.com", smtp_from_address="noreply@example.com")
    msg = mailer.build_message(
        cfg,
        to_email="c@example.com",
        to_user_id=uuid.uuid4(),
        subject="s",
        content_html="h",
        content_text="t",
    )
    assert msg["From"] == "noreply@example.com"


def test_build_message_uses_gmail_sender_email_in_gmail_oauth_mode() -> None:
    cfg = _cfg(
        smtp_from_address="noreply@example.com",  # must NOT win over gmail mode
        gmail_service_account_json=json.dumps(fake_service_account_info()),
        gmail_sender_email="billing@example.com",
    )
    msg = mailer.build_message(
        cfg,
        to_email="c@example.com",
        to_user_id=uuid.uuid4(),
        subject="s",
        content_html="h",
        content_text="t",
    )
    assert msg["From"] == "billing@example.com"


# -- _build_signed_jwt: a real, independently-verifiable RS256 assertion ----


def test_build_signed_jwt_produces_three_dot_separated_parts() -> None:
    info = fake_service_account_info()
    token = mailer._build_signed_jwt(
        info,
        sender_email="billing@example.com",
        scope=mailer._GMAIL_SEND_SCOPE,
        audience="https://oauth2.googleapis.com/token",
    )
    assert token.count(".") == 2


def test_build_signed_jwt_header_and_claims_are_correct() -> None:
    info = fake_service_account_info()
    token = mailer._build_signed_jwt(
        info,
        sender_email="billing@example.com",
        scope=mailer._GMAIL_SEND_SCOPE,
        audience="https://oauth2.googleapis.com/token",
    )
    header_b64, claims_b64, _sig_b64 = token.split(".")

    def _decode(part: str) -> dict:
        padded = part + "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))

    header = _decode(header_b64)
    claims = _decode(claims_b64)
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert claims["iss"] == info["client_email"]
    assert claims["sub"] == "billing@example.com"
    assert claims["scope"] == mailer._GMAIL_SEND_SCOPE
    assert claims["aud"] == "https://oauth2.googleapis.com/token"
    assert claims["exp"] == claims["iat"] + 3600


def test_build_signed_jwt_signature_actually_verifies() -> None:
    """The one test that would catch a subtly wrong signing scheme
    (wrong padding, wrong hash, wrong signing input) that "looks like a
    JWT" but a real RS256 verifier -- i.e. the real Google token
    endpoint -- would reject outright. Verifies against the SAME
    keypair's public half, independent of mailer.py's own signing code
    path (uses the low-level cryptography primitives directly, not
    mailer._build_signed_jwt's internals).
    """
    info = fake_service_account_info()
    token = mailer._build_signed_jwt(
        info,
        sender_email="billing@example.com",
        scope=mailer._GMAIL_SEND_SCOPE,
        audience="https://oauth2.googleapis.com/token",
    )
    header_b64, claims_b64, sig_b64 = token.split(".")
    signing_input = f"{header_b64}.{claims_b64}".encode("ascii")
    padded_sig = sig_b64 + "=" * (-len(sig_b64) % 4)
    signature = base64.urlsafe_b64decode(padded_sig)

    private_key = serialization.load_pem_private_key(
        info["private_key"].encode("utf-8"), password=None
    )
    public_key = private_key.public_key()
    # Raises InvalidSignature if this JWT would NOT actually be accepted
    # by a real RS256 verifier -- no exception means it's a genuinely
    # valid signature over the exact signing input.
    public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())


def test_build_signed_jwt_rejects_tampered_payload() -> None:
    """Sanity check the other direction -- a tampered signing input must
    NOT verify, so the "verifies" test above isn't accidentally trivially
    true (e.g. a verify() that never actually raises).
    """
    info = fake_service_account_info()
    token = mailer._build_signed_jwt(
        info,
        sender_email="billing@example.com",
        scope=mailer._GMAIL_SEND_SCOPE,
        audience="https://oauth2.googleapis.com/token",
    )
    header_b64, claims_b64, sig_b64 = token.split(".")
    padded_sig = sig_b64 + "=" * (-len(sig_b64) % 4)
    signature = base64.urlsafe_b64decode(padded_sig)

    private_key = serialization.load_pem_private_key(
        info["private_key"].encode("utf-8"), password=None
    )
    public_key = private_key.public_key()
    tampered_input = f"{header_b64}.{claims_b64}TAMPERED".encode("ascii")
    with pytest.raises(InvalidSignature):
        public_key.verify(
            signature, tampered_input, padding.PKCS1v15(), hashes.SHA256()
        )
