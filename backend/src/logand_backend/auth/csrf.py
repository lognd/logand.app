from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def generate_csrf_secret() -> str:
    return secrets.token_urlsafe(32)


def verify_csrf(request: Request) -> None:
    if request.method in _SAFE_METHODS:
        return
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_value or not header_value or not hmac.compare_digest(cookie_value, header_value):
        raise HTTPException(status_code=403, detail="csrf token missing or mismatched")
