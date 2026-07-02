from __future__ import annotations

import asyncio
import hashlib
import hmac
import smtplib
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from uuid import UUID

from logand_backend.app.config import AppConfig

# Real stdlib email.message.EmailMessage (not string-templated HTML) is
# what actually produces a correct multipart/alternative MIME structure
# (boundary, Content-Type, Content-Transfer-Encoding all handled
# correctly) -- "parsable by other automated tools" was an explicit
# requirement, and hand-built MIME is exactly the kind of thing that looks
# fine in a browser preview while being subtly malformed to a strict
# parser.


def is_configured(cfg: AppConfig) -> bool:
    """True once a real SMTP host is configured -- every notify_* call in
    domain/notifications/notify.py checks this first, same graceful
    "not hooked up yet" pattern as domain/payments/providers/paypal.py's
    is_configured. Nothing in the invoice/payment flow depends on this
    being true.
    """
    return bool(cfg.smtp_host)


def sign_unsubscribe_token(user_id: UUID, cfg: AppConfig) -> str:
    """"{user_id}.{hmac-sha256 hex digest}" -- verifiable without a DB
    lookup (a lookup is still done afterward, but only to actually apply
    the opt-out, not to validate the token itself), and without a separate
    secrets table: reuses session_secret as the HMAC key, the same
    already-required-to-be-set secret sessions.py signs session tokens
    with.
    """
    user_id_str = str(user_id)
    sig = hmac.new(
        cfg.session_secret.encode("utf-8"), user_id_str.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{user_id_str}.{sig}"


def verify_unsubscribe_token(token: str, cfg: AppConfig) -> UUID | None:
    """None for any malformed or tampered token -- api/notifications.py
    treats that as 400, never distinguishing "malformed" from "wrong
    signature" in the response.
    """
    try:
        user_id_str, sig = token.rsplit(".", 1)
        user_id = UUID(user_id_str)
    except ValueError:
        return None
    expected = hmac.new(
        cfg.session_secret.encode("utf-8"), user_id_str.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
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
    msg["From"] = cfg.smtp_from_address
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
    than gracefully no-op-ing, since a caller reaching here with no
    smtp_host set is itself the bug to catch. asyncio.to_thread, not a bare
    call -- smtplib is fully synchronous (blocking DNS + socket I/O), same
    reasoning as render_invoice_pdf's own to_thread call for latexmk.
    """
    msg = build_message(
        cfg,
        to_email=to_email,
        to_user_id=to_user_id,
        subject=subject,
        content_html=content_html,
        content_text=content_text,
    )
    await asyncio.to_thread(_send_sync, cfg, msg)
