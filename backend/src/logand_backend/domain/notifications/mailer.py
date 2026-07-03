from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import smtplib
import ssl
import time
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from uuid import UUID

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from logand_backend.app.config import AppConfig

# Real stdlib email.message.EmailMessage (not string-templated HTML) is
# what actually produces a correct multipart/alternative MIME structure
# (boundary, Content-Type, Content-Transfer-Encoding all handled
# correctly) -- "parsable by other automated tools" was an explicit
# requirement, and hand-built MIME is exactly the kind of thing that looks
# fine in a browser preview while being subtly malformed to a strict
# parser.

# Google's real OAuth2 token endpoint and Gmail API host -- see
# AppConfig.gmail_token_api_base/gmail_api_base's own doc comment for why
# these are two separate overridable bases, only ever overridden in
# test/CI to point at testing/fake_gmail.py's local double.
_GOOGLE_TOKEN_API_BASE = "https://oauth2.googleapis.com"
_GMAIL_API_BASE = "https://gmail.googleapis.com"
_GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

logger = logging.getLogger(__name__)


def is_configured(cfg: AppConfig) -> bool:
    """True once a real mail transport is configured -- either plain SMTP
    or Gmail OAuth2 (see _gmail_oauth_configured). Every notify_* call in
    domain/notifications/notify.py checks this first, same graceful "not
    hooked up yet" pattern as domain/payments/providers/paypal.py's
    is_configured. Nothing in the invoice/payment flow depends on this
    being true.
    """
    return bool(cfg.smtp_host) or _gmail_oauth_configured(cfg)


def _gmail_oauth_configured(cfg: AppConfig) -> bool:
    """Both fields required together -- a service-account key with no
    mailbox to impersonate (or vice versa) can't actually send anything,
    so treat it the same as neither being set rather than failing later
    with a confusing error.
    """
    return bool(cfg.gmail_service_account_json and cfg.gmail_sender_email)


# Coarse expiry window for unsubscribe links: long enough that a
# recently-sent invoice/receipt email's footer link never nags a real
# customer, short enough that a token captured from a stale forwarded
# thread or mail archive eventually stops being usable -- see
# FINDINGS.md L2. Granularity is a day, not a timestamp, so the token
# stays short and doesn't leak send-time precision.
_UNSUBSCRIBE_TOKEN_MAX_AGE_DAYS = 180


def sign_unsubscribe_token(user_id: UUID, cfg: AppConfig) -> str:
    """ "{user_id}.{issued_epoch_day}.{hmac-sha256 hex digest}" --
    verifiable without a DB lookup (a lookup is still done afterward, but
    only to actually apply the opt-out, not to validate the token itself),
    and without a separate secrets table: reuses session_secret as the
    HMAC key, the same already-required-to-be-set secret sessions.py signs
    session tokens with. Includes the day the token was issued so
    verify_unsubscribe_token can reject tokens older than
    _UNSUBSCRIBE_TOKEN_MAX_AGE_DAYS -- previously this was a static
    per-user value with no expiry at all.
    """
    user_id_str = str(user_id)
    issued_epoch_day = int(time.time() // 86400)
    payload = f"{user_id_str}.{issued_epoch_day}"
    sig = hmac.new(
        cfg.session_secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{sig}"


def verify_unsubscribe_token(token: str, cfg: AppConfig) -> UUID | None:
    """None for any malformed, tampered, or expired token --
    api/notifications.py treats that as 400, never distinguishing
    "malformed", "wrong signature", or "expired" in the response (the
    existing "invalid or expired unsubscribe link" copy already covers
    all three).
    """
    try:
        user_id_str, issued_epoch_day_str, sig = token.rsplit(".", 2)
        user_id = UUID(user_id_str)
        issued_epoch_day = int(issued_epoch_day_str)
    except ValueError:
        return None
    payload = f"{user_id_str}.{issued_epoch_day}"
    expected = hmac.new(
        cfg.session_secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    current_epoch_day = int(time.time() // 86400)
    if current_epoch_day - issued_epoch_day > _UNSUBSCRIBE_TOKEN_MAX_AGE_DAYS:
        return None
    return user_id


def _footer_html(cfg: AppConfig, unsubscribe_url: str) -> str:
    return (
        "<hr>"
        f"<p>{cfg.invoice_business_name}"
        + (f", {cfg.mailing_address}" if cfg.mailing_address else "")
        + "</p>"
        f'<p><a href="{unsubscribe_url}">Unsubscribe</a> from these emails.</p>'
    )


def _footer_text(cfg: AppConfig, unsubscribe_url: str) -> str:
    address = f", {cfg.mailing_address}" if cfg.mailing_address else ""
    return (
        f"\n\n--\n{cfg.invoice_business_name}{address}\n"
        f"Unsubscribe from these emails: {unsubscribe_url}\n"
    )


def build_message(
    cfg: AppConfig,
    *,
    to_email: str,
    to_user_id: UUID,
    subject: str,
    content_html: str,
    content_text: str,
) -> EmailMessage:
    token = sign_unsubscribe_token(to_user_id, cfg)
    unsubscribe_url = f"{cfg.public_base_url}/api/unsubscribe?token={token}"

    # max_line_length=998 (RFC 5322's hard limit, not the usual 78
    # "recommended" wrap) -- the default policy's header folding falls back
    # to RFC 2047 encoded-word wrapping for a long header with no
    # whitespace to break on (exactly what a bare "<https://...token>" URL
    # is), which would leave List-Unsubscribe unparsable by mail clients
    # expecting a literal "<url>" -- the entire reason this header exists.
    msg = EmailMessage(policy=policy.default.clone(max_line_length=998))
    msg["Subject"] = subject
    # Gmail OAuth2 (domain-wide delegation) can only send AS the
    # impersonated mailbox itself, unless that mailbox has a separate
    # "Send mail as" alias configured -- keep it simple and use the
    # impersonated account as From in that mode, same identity the JWT's
    # own "sub" claim asserts.
    msg["From"] = (
        cfg.gmail_sender_email
        if _gmail_oauth_configured(cfg)
        else cfg.smtp_from_address
    )
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    # RFC 8058 one-click unsubscribe -- both headers required together, so
    # a compliant mail client (Gmail, Outlook, etc.) can show its own
    # "Unsubscribe" button and fire a bodyless POST at unsubscribe_url
    # without the user ever opening the email.
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    msg.set_content(content_text + _footer_text(cfg, unsubscribe_url))
    msg.add_alternative(
        f"<html><body>{content_html}{_footer_html(cfg, unsubscribe_url)}</body></html>",
        subtype="html",
    )
    return msg


def _send_sync(cfg: AppConfig, msg: EmailMessage) -> None:
    assert cfg.smtp_host is not None
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as client:
        if cfg.smtp_use_tls:
            client.starttls(context=ssl.create_default_context())
        if cfg.smtp_username and cfg.smtp_password:
            client.login(cfg.smtp_username, cfg.smtp_password)
        client.send_message(msg)


def _b64url(data: bytes) -> bytes:
    """Base64url WITHOUT padding -- both JWT's own encoding (RFC 7519) and
    the Gmail API's `raw` field (RFC 4648 sec 5, "base64url encoding as
    described in RFC 4648, ... with URL and filename-safe alphabet")
    require this, not stdlib's default `+`/`/`-using base64.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _build_signed_jwt(
    service_account_info: dict, *, sender_email: str, scope: str, audience: str
) -> str:
    """Hand-rolled RS256 JWT Bearer assertion (RFC 7523) for a Google
    service account -- deliberately not the google-auth/google-api-
    python-client SDKs (a much heavier dependency than this app pulls in
    anywhere else; domain/payments/providers/paypal.py's own OAuth2
    client-credentials flow is hand-rolled via httpx the same way, this
    mirrors that). "sub" is what makes this domain-wide delegation --
    without it Google authenticates AS the service account itself, which
    has no mailbox of its own to send from.
    """
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": service_account_info["client_email"],
        "scope": scope,
        "aud": audience,
        "iat": now,
        "exp": now + 3600,
        "sub": sender_email,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + b"."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    )
    private_key = serialization.load_pem_private_key(
        service_account_info["private_key"].encode("utf-8"), password=None
    )
    assert isinstance(private_key, RSAPrivateKey)
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return (signing_input + b"." + _b64url(signature)).decode("ascii")


# Process-local cache for the Gmail access token, keyed by (client_email,
# sender_email, token_url) so a config change (e.g. between test doubles)
# can't reuse a stale token minted for a different identity. Populated by
# _get_gmail_access_token below. See that function's doc comment for why
# this exists: notify_dispute_updated (notify.py) fans a single dispute
# event out to EVERY admin, so without a cache one notification burst
# means N sequential token exchanges instead of 1 (FINDINGS.md L1).
_gmail_token_cache: dict[tuple[str, str, str], tuple[str, float]] = {}
# Refresh this many seconds before actual expiry, so a token handed out
# near the end of its life doesn't die mid-request.
_GMAIL_TOKEN_REFRESH_SKEW = 60.0


def _gmail_cache_key(cfg: AppConfig) -> tuple[str, str, str]:
    """Computes the cache key for the current Gmail service-account
    identity, so a 401 handler can evict exactly the entry that just
    proved stale without recomputing token-exchange internals.
    """
    assert cfg.gmail_service_account_json is not None
    assert cfg.gmail_sender_email is not None
    info = json.loads(cfg.gmail_service_account_json)
    token_url = f"{cfg.gmail_token_api_base or _GOOGLE_TOKEN_API_BASE}/token"
    return (info["client_email"], cfg.gmail_sender_email, token_url)


async def _get_gmail_access_token(
    cfg: AppConfig, client: httpx.AsyncClient, *, force_refresh: bool = False
) -> str:
    """Exchanges a JWT Bearer assertion for a short-lived access token,
    reusing a cached token for its remaining lifetime instead of hitting
    Google on every send. This IS a hot-ish path in one case: a dispute
    event notifies every admin (notify.py's notify_dispute_updated), so a
    single Stripe webhook can trigger many sends back to back -- caching
    collapses that burst to one token exchange instead of N (FINDINGS.md
    L1). The cache is process-local and unsynchronized; a rare concurrent
    miss just costs one extra exchange, not a correctness problem.

    `force_refresh` skips the cache lookup entirely -- used by
    `_send_via_gmail_api` after a 401 to mint a fresh token instead of
    re-returning the same dead one (FINDINGS.md M1).
    """
    assert cfg.gmail_service_account_json is not None
    assert cfg.gmail_sender_email is not None
    info = json.loads(cfg.gmail_service_account_json)
    token_url = f"{cfg.gmail_token_api_base or _GOOGLE_TOKEN_API_BASE}/token"
    cache_key = (info["client_email"], cfg.gmail_sender_email, token_url)

    if not force_refresh:
        cached = _gmail_token_cache.get(cache_key)
        if cached is not None:
            token, expires_at = cached
            if time.monotonic() < expires_at:
                return token

    assertion = _build_signed_jwt(
        info,
        sender_email=cfg.gmail_sender_email,
        scope=_GMAIL_SEND_SCOPE,
        audience=token_url,
    )
    resp = await client.post(
        token_url,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
    )
    resp.raise_for_status()
    body = resp.json()
    token = body["access_token"]
    expires_in = float(body.get("expires_in", 3600))
    _gmail_token_cache[cache_key] = (
        token,
        time.monotonic() + max(expires_in - _GMAIL_TOKEN_REFRESH_SKEW, 0.0),
    )
    return token


async def _send_via_gmail_api(cfg: AppConfig, msg: EmailMessage) -> None:
    """Sends through the Gmail REST API (users.messages.send) instead of
    raw SMTP -- see AppConfig.gmail_service_account_json's own doc
    comment for why: Google retired password/app-password SMTP auth for
    Workspace accounts entirely (March 2025), OAuth2 is the only way
    left to send as a Workspace mailbox at all.
    """
    raw = _b64url(msg.as_bytes()).decode("ascii")
    api_base = cfg.gmail_api_base or _GMAIL_API_BASE
    async with httpx.AsyncClient(timeout=10.0) as client:
        token = await _get_gmail_access_token(cfg, client)
        resp = await client.post(
            f"{api_base}/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
        )
        if resp.status_code == 401:
            # Cached token was revoked/rotated out from under us (FINDINGS.md
            # M1). Evict it so every subsequent send doesn't keep replaying
            # the same dead token for up to ~59 minutes, mint a fresh one,
            # and retry exactly once.
            logger.warning(
                "gmail_api_401_evicting_cached_token",
                extra={"cache_key": _gmail_cache_key(cfg)[:2]},
            )
            _gmail_token_cache.pop(_gmail_cache_key(cfg), None)
            token = await _get_gmail_access_token(cfg, client, force_refresh=True)
            resp = await client.post(
                f"{api_base}/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {token}"},
                json={"raw": raw},
            )
        resp.raise_for_status()


async def send_email(
    cfg: AppConfig,
    *,
    to_email: str,
    to_user_id: UUID,
    subject: str,
    content_html: str,
    content_text: str,
) -> None:
    """Callers must check is_configured(cfg) first -- this asserts rather
    than gracefully no-op-ing, since a caller reaching here with neither
    transport configured is itself the bug to catch. Gmail OAuth2 takes
    precedence over plain SMTP if both happen to be set (see
    _gmail_oauth_configured). The SMTP path still uses asyncio.to_thread
    (smtplib is fully synchronous -- blocking DNS + socket I/O, same
    reasoning as render_invoice_pdf's own to_thread call for latexmk);
    the Gmail API path is natively async via httpx, same as
    domain/payments/providers/paypal.py's own calls.
    """
    msg = build_message(
        cfg,
        to_email=to_email,
        to_user_id=to_user_id,
        subject=subject,
        content_html=content_html,
        content_text=content_text,
    )
    if _gmail_oauth_configured(cfg):
        await _send_via_gmail_api(cfg, msg)
    else:
        await asyncio.to_thread(_send_sync, cfg, msg)
