from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
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


# -- sign_unsubscribe_token / verify_unsubscribe_token ----------------------


def test_unsubscribe_token_round_trips_immediately() -> None:
    cfg = _cfg(session_secret="test-secret")
    user_id = uuid.uuid4()
    token = mailer.sign_unsubscribe_token(user_id, cfg)
    assert mailer.verify_unsubscribe_token(token, cfg) == user_id


def test_unsubscribe_token_rejects_expired_token() -> None:
    """FINDINGS.md M2: a signature-valid token issued more than
    _UNSUBSCRIBE_TOKEN_MAX_AGE_DAYS days ago must be rejected. Hand-build
    the token with the real HMAC so the signature is valid but the day is
    stale, rather than monkeypatching time.time (which would also perturb
    the "current day" side of the comparison).
    """
    cfg = _cfg(session_secret="test-secret")
    user_id = uuid.uuid4()
    stale_day = int(time.time() // 86400) - mailer._UNSUBSCRIBE_TOKEN_MAX_AGE_DAYS - 1
    payload = f"{user_id}.{stale_day}"
    sig = hmac.new(
        cfg.session_secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    stale_token = f"{payload}.{sig}"
    assert mailer.verify_unsubscribe_token(stale_token, cfg) is None


def test_unsubscribe_token_accepts_token_at_the_age_boundary() -> None:
    """Exactly _UNSUBSCRIBE_TOKEN_MAX_AGE_DAYS days old is still valid --
    the check is strictly-greater-than, so the boundary itself must not
    regress to a rejection."""
    cfg = _cfg(session_secret="test-secret")
    user_id = uuid.uuid4()
    boundary_day = int(time.time() // 86400) - mailer._UNSUBSCRIBE_TOKEN_MAX_AGE_DAYS
    payload = f"{user_id}.{boundary_day}"
    sig = hmac.new(
        cfg.session_secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    boundary_token = f"{payload}.{sig}"
    assert mailer.verify_unsubscribe_token(boundary_token, cfg) == user_id


def test_unsubscribe_token_rejects_tampered_day() -> None:
    """A token whose issued_epoch_day was rewritten to look fresh must
    fail signature verification -- the day is part of the signed payload,
    not a free-standing field."""
    cfg = _cfg(session_secret="test-secret")
    user_id = uuid.uuid4()
    token = mailer.sign_unsubscribe_token(user_id, cfg)
    user_id_str, issued_day_str, sig = token.rsplit(".", 2)
    tampered_day = int(issued_day_str) + 1
    tampered_token = f"{user_id_str}.{tampered_day}.{sig}"
    assert mailer.verify_unsubscribe_token(tampered_token, cfg) is None


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
