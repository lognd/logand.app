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
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape as html_escape
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
    # html_escape on business_name/mailing_address -- both are admin-
    # configured (not attacker-controlled from a customer-facing form),
    # but escaping is nearly free and this is the one place free-form
    # admin text reaches raw HTML, so there's no reason to trust it any
    # more than genuinely untrusted input would be trusted elsewhere.
    business = html_escape(cfg.invoice_business_name)
    address = f", {html_escape(cfg.mailing_address)}" if cfg.mailing_address else ""
    return (
        f'<p style="margin:0 0 6px;">{business}{address}</p>'
        f'<p style="margin:0;">'
        f'<a href="{html_escape(unsubscribe_url, quote=True)}" '
        f'style="color:inherit;">Unsubscribe</a>'
        " from these emails.</p>"
    )


def _footer_text(cfg: AppConfig, unsubscribe_url: str) -> str:
    address = f", {cfg.mailing_address}" if cfg.mailing_address else ""
    return (
        f"\n\n--\n{cfg.invoice_business_name}{address}\n"
        f"Unsubscribe from these emails: {unsubscribe_url}\n"
    )


# Gruvbox palette (see frontend/src/styles/tokens.css's own doc comment
# and frontend/src/app/routes/public/TerminalWindow.tsx) -- the same
# Ubuntu-GNOME-styled terminal window chrome the site itself uses,
# reused here so a notification email reads as unmistakably "this app"
# rather than a generic transactional email template. The site itself
# only implements the dark palette so far (tokens.css: "Light theme is
# deferred"); email dark-mode support is common enough in real mail
# clients (Apple Mail, iOS Mail, Outlook.com) that shipping email-only
# without waiting on the site's own light theme is worth doing now.
#
# The light values are still real Gruvbox Light tokens (bg2/bg0/bg1/
# fg0/bg4/bg3/faded-green -- see the official palette), just picked for
# more separation between page/titlebar/card than the flattest official
# assignment gives: the first pass used bg1 for both the page and the
# titlebar (identical), which read as bland/washed-out in review. Using
# bg2 (darker) for the page frame, bg1 for the titlebar, and bg0 for the
# card gives three visibly distinct tan bands instead of two.
_LIGHT = {
    "page_bg": "#d5c4a1",
    "card_bg": "#fbf1c7",
    "titlebar_bg": "#ebdbb2",
    "fg": "#282828",
    "muted": "#665c54",
    "border": "#bdae93",
    "accent_green": "#66800b",
}
_DARK = {
    "page_bg": "#1d2021",
    "card_bg": "#282828",
    "titlebar_bg": "#3c3836",
    "fg": "#ebdbb2",
    "muted": "#a89984",
    "border": "#504945",
    "accent_green": "#b8bb26",
}
# Monospace stack matching the site's own (frontend/src/styles/tailwind.css
# imports JetBrains Mono as a web font) -- email clients don't reliably
# load web fonts at all, so this is a graceful-degradation stack: real
# JetBrains Mono for a recipient who happens to have it installed
# locally, falling through to each platform's own default monospace
# otherwise. Never assumed to actually render as JetBrains Mono.
_MONO_STACK = (
    "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
)
_TITLE_MAX_LEN = 46


def _window_title(subject: str) -> str:
    """Truncates like a real terminal window truncates a long title/path
    -- the full, untruncated text is still what the mail client shows in
    its own UI (the real Subject header); this is purely the in-body
    titlebar decoration.
    """
    if len(subject) <= _TITLE_MAX_LEN:
        return subject
    return subject[: _TITLE_MAX_LEN - 3] + "..."


def _wrap_terminal_shell(*, subject: str, content_html: str, footer_html: str) -> str:
    """Wraps message-specific `content_html` in a light/dark-aware,
    Ubuntu-terminal-styled card matching the site's own TerminalWindow
    chrome: a titlebar (title left, monochrome window-control glyphs
    right, exactly TerminalWindow.tsx's own GNOME-style ordering) over a
    monospace body.

    Table-based layout throughout (not flexbox/grid, which Outlook
    desktop's Word rendering engine doesn't support at all) -- this is
    the standard email-HTML compatibility pattern, not an oversight.
    Every color is set twice: once as an inline style (the default every
    client renders, including ones with zero dark-mode awareness) and
    once in the `<style>` block's `@media (prefers-color-scheme: dark)`
    rule with `!important` (the only way to override an inline style
    from a stylesheet) -- `!important` here is correct email-HTML
    practice, not a specificity hack to be suspicious of. The
    `color-scheme`/`supported-color-schemes` meta tags are what actually
    make Apple Mail/iOS Mail/Outlook.com honor the media query at all;
    without them some clients ignore it and force one mode.
    """
    title = html_escape(_window_title(subject))
    table_open = '<table role="presentation" width="100%" cellpadding="0" '
    table_open += 'cellspacing="0" border="0">'
    dot = '<span class="ln-dot" style="color:{muted}; margin-left:10px;">{glyph}</span>'
    dots = "".join(
        dot.format(muted=_LIGHT["muted"], glyph=glyph)
        for glyph in ("&#8722;", "&#9633;", "&#215;")
    )
    lines = [
        "<!doctype html>",
        "<html>",
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        '<meta name="supported-color-schemes" content="light dark">',
        "<style>",
        "@media (prefers-color-scheme: dark) {",
        f"  .ln-page {{ background-color: {_DARK['page_bg']} !important; }}",
        f"  .ln-card {{ background-color: {_DARK['card_bg']} !important;",
        f"    border-color: {_DARK['border']} !important; }}",
        f"  .ln-titlebar {{ background-color: {_DARK['titlebar_bg']} !important;",
        f"    border-color: {_DARK['border']} !important; }}",
        f"  .ln-titlebar *, .ln-dot {{ color: {_DARK['muted']} !important; }}",
        f"  .ln-text {{ color: {_DARK['fg']} !important;",
        f"    background-color: {_DARK['card_bg']} !important; }}",
        f"  .ln-muted {{ color: {_DARK['muted']} !important; }}",
        f"  .ln-footer {{ background-color: {_DARK['page_bg']} !important; }}",
        f"  .ln-cta {{ color: {_DARK['accent_green']} !important; }}",
        "}",
        "</style>",
        "</head>",
        f'<body class="ln-page" style="margin:0; padding:24px 12px; '
        f'background-color:{_LIGHT["page_bg"]};">',
        table_open,
        '<tr><td align="center">',
        '<table role="presentation" width="600" cellpadding="0" '
        'cellspacing="0" border="0" style="max-width:600px; width:100%;">',
        f'<tr><td class="ln-card" bgcolor="{_LIGHT["card_bg"]}" '
        f'style="background-color:{_LIGHT["card_bg"]}; '
        f'border:1px solid {_LIGHT["border"]}; border-radius:6px;">',
        table_open,
        f'<tr><td class="ln-titlebar" bgcolor="{_LIGHT["titlebar_bg"]}" '
        f'style="background-color:{_LIGHT["titlebar_bg"]}; '
        f"border-bottom:1px solid {_LIGHT['border']}; "
        f'border-radius:6px 6px 0 0; padding:10px 16px;">',
        table_open,
        "<tr>",
        f'<td style="font-family:{_MONO_STACK}; '
        f'font-size:12px; color:{_LIGHT["muted"]};">{title}</td>',
        f'<td align="right" style="white-space:nowrap; '
        f'font-family:{_MONO_STACK}; font-size:13px; color:{_LIGHT["muted"]};">'
        f"{dots}</td>",
        "</tr>",
        "</table>",
        "</td></tr>",
        f'<tr><td class="ln-text" bgcolor="{_LIGHT["card_bg"]}" '
        f'style="background-color:{_LIGHT["card_bg"]}; padding:24px 20px;">',
        f'<div style="font-family:{_MONO_STACK}; '
        f'font-size:14px; line-height:1.6; color:{_LIGHT["fg"]};">',
        content_html,
        "</div>",
        "</td></tr>",
        "</table>",
        "</td></tr>",
        f'<tr><td class="ln-footer" bgcolor="{_LIGHT["page_bg"]}" '
        f'style="background-color:{_LIGHT["page_bg"]}; padding:16px 8px 0;">',
        f'<div class="ln-muted" style="font-family:{_MONO_STACK}; '
        f'font-size:11px; line-height:1.6; color:{_LIGHT["muted"]};">',
        footer_html,
        "</div>",
        "</td></tr>",
        "</table>",
        "</td></tr>",
        "</table>",
        "</body>",
        "</html>",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class EmailAttachment:
    """A real MIME attachment (distinct from the multipart/alternative
    html/plain BODY every message already has). `maintype`/`subtype`
    are the two halves of the attachment's own Content-Type (e.g.
    "application"/"pdf", "text"/"plain", "application"/"json") --
    `EmailMessage.add_attachment` needs them split, not as one
    "application/pdf" string.
    """

    filename: str
    content: bytes
    maintype: str
    subtype: str


def build_message(
    cfg: AppConfig,
    *,
    to_email: str,
    to_user_id: UUID,
    subject: str,
    content_html: str,
    content_text: str,
    attachments: tuple[EmailAttachment, ...] = (),
) -> EmailMessage:
    """`attachments` are added in the given order, after the html/plain
    body -- `EmailMessage.add_attachment` appends each as its own MIME
    part (promoting the message to multipart/mixed wrapping the
    multipart/alternative body), so callers control ordering simply by
    the order they pass attachments in. Callers that want a specific
    attachment last (e.g. notify.py puts "for-robots.json" last, after
    the PDF and plaintext copies, so a human skimming an attachment list
    sees the human-readable ones first) just order the tuple that way.
    """
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
        _wrap_terminal_shell(
            subject=subject,
            content_html=content_html,
            footer_html=_footer_html(cfg, unsubscribe_url),
        ),
        subtype="html",
    )
    for attachment in attachments:
        msg.add_attachment(
            attachment.content,
            maintype=attachment.maintype,
            subtype=attachment.subtype,
            filename=attachment.filename,
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
    attachments: tuple[EmailAttachment, ...] = (),
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
        attachments=attachments,
    )
    if _gmail_oauth_configured(cfg):
        await _send_via_gmail_api(cfg, msg)
    else:
        await asyncio.to_thread(_send_sync, cfg, msg)
