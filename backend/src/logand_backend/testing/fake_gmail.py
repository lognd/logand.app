from __future__ import annotations

import base64
from email import message_from_bytes, policy
from email.message import EmailMessage

from fastapi import FastAPI, Request, Response

# A local HTTP double for the slice of Google's real OAuth2 token endpoint
# + Gmail API this backend calls (domain/notifications/mailer.py) -- same
# reasoning as testing/fake_stripe.py/testing/fake_paypal.py's own doc
# comments: the real httpx-based code runs unmodified against this, just
# pointed at a different host (AppConfig.gmail_token_api_base/
# gmail_api_base), so a system test exercises the real request/response
# wire format (a real signed JWT posted to /token, a real base64url `raw`
# MIME blob posted to /gmail/v1/users/me/messages/send) instead of mocking
# mailer.py's own functions away.
#
# Deliberately does NOT verify the JWT's RS256 signature -- that would
# require this double to know the service account's public key, which
# defeats the point of a test double (the whole point is to run against
# throwaway test key material, see conftest.py's fake_gmail_service_account
# fixture). What real Google enforces (a validly-shaped, correctly-signed
# assertion) is exercised by unit tests in tests/unit/test_mailer.py
# instead, which verify the JWT's own structure directly.
app = FastAPI(title="fake-gmail (test double, not real Google)")

_FAKE_ACCESS_TOKEN = "fake-gmail-access-token"
# In-memory only, module-level state for the lifetime of this process --
# same convention as fake_paypal.py's _orders.
_sent_messages: list[EmailMessage] = []
# When > 0, the next `_reject_401_remaining` sends return 401 instead of
# succeeding, regardless of the bearer token presented -- lets a system
# test simulate Google revoking/rotating an outstanding access token out
# from under mailer.py's process-local cache (FINDINGS.md M1) without
# needing to fake an actually-expired-looking token.
_reject_401_remaining = 0


@app.post("/token")
async def token(request: Request) -> dict:
    body = await request.form()
    # Not a real signature check (see module doc comment) -- but a wrong
    # grant_type would mean mailer.py itself is malformed, not a Google-
    # side failure, so this still catches THAT class of bug.
    assert body.get("grant_type") == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert body.get("assertion")
    return {
        "access_token": _FAKE_ACCESS_TOKEN,
        "token_type": "Bearer",
        "expires_in": 3600,
    }


@app.post("/gmail/v1/users/me/messages/send")
async def send_message(request: Request, response: Response) -> dict | None:
    global _reject_401_remaining
    if _reject_401_remaining > 0:
        _reject_401_remaining -= 1
        response.status_code = 401
        return None
    auth = request.headers.get("authorization", "")
    assert auth == f"Bearer {_FAKE_ACCESS_TOKEN}", (
        "fake-gmail: missing or wrong bearer token"
    )
    body = await request.json()
    raw = body["raw"]
    # Real Gmail API `raw` is base64url, no padding -- mirrors
    # mailer.py's own _b64url encoding, decoded back with a padding fixup
    # since Python's b64decode requires padding but urlsafe_b64encode's
    # output (after mailer.py's own .rstrip(b"=")) doesn't have any.
    padded = raw + "=" * (-len(raw) % 4)
    content = base64.urlsafe_b64decode(padded)
    msg = message_from_bytes(content, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    _sent_messages.append(msg)
    return {"id": "fake-gmail-message-id", "threadId": "fake-gmail-thread-id"}


def sent_messages() -> list[EmailMessage]:
    """Test-only accessor -- same shape as FakeSmtpServer.messages, so
    system tests can share assertion helpers between the SMTP and Gmail
    OAuth2 transports (see tests/system/test_notifications.py and
    tests/system/test_notifications_gmail.py).
    """
    return _sent_messages


def force_401_once(times: int = 1) -> None:
    """Test-only control: makes the next `times` calls to the send
    endpoint return 401 regardless of the bearer token, simulating Google
    revoking/rotating a token mailer.py still has cached (FINDINGS.md M1).
    """
    global _reject_401_remaining
    _reject_401_remaining = times


def reset() -> None:
    """Module-level state persists for the process lifetime (see
    _sent_messages' own comment) -- tests must reset between cases,
    same convention fake_paypal.py's _orders would need if two tests in
    the same session cared about seeing an empty state.
    """
    global _reject_401_remaining
    _sent_messages.clear()
    _reject_401_remaining = 0
