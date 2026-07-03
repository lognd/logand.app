from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def generate_csrf_secret() -> str:
    return secrets.token_urlsafe(32)


def verify_csrf(request: Request, expected_secret: str | None = None) -> None:
    """Double-submit check: cookie and header must match.

    When `expected_secret` is given (the real session's own csrf_secret,
    looked up server-side by app.py's middleware), the cookie AND header
    must both match THAT value too -- not just each other. Without this,
    double-submit alone only proves "whoever sent this request could read
    this app's own cookies for this origin," which same-site cookie
    scoping already mostly guarantees; it does not prove the CSRF token
    presented is the one this app itself issued for the CURRENT session.
    A cookie the browser sends but that doesn't match the session's own
    stored secret (a stale token cookie a session/logout cycle left
    behind, or a cookie an attacker with any first-party write access --
    a subdomain, a XSS elsewhere -- could plant) would otherwise still
    pass a pure cookie==header check.

    `expected_secret=None` is the fallback for a request app.py's
    middleware couldn't resolve a live session for (no session cookie at
    all, or a session that's already expired/invalid) -- pure double-
    submit is still enforced in that case so this never becomes a no-op,
    but there's no session-bound secret to check the pair against yet.
    """
    if request.method in _SAFE_METHODS:
        return
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_value or not header_value:
        raise HTTPException(status_code=403, detail="csrf token missing or mismatched")
    if not hmac.compare_digest(cookie_value, header_value):
        raise HTTPException(status_code=403, detail="csrf token missing or mismatched")
    if expected_secret is not None and not hmac.compare_digest(
        cookie_value, expected_secret
    ):
        raise HTTPException(status_code=403, detail="csrf token missing or mismatched")
