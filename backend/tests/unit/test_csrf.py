from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from logand_backend.auth.csrf import generate_csrf_secret, verify_csrf


def test_generate_csrf_secret_is_unique_and_nonempty() -> None:
    a = generate_csrf_secret()
    b = generate_csrf_secret()
    assert a != b
    assert len(a) > 16


def _make_request(method: str, cookies: dict, headers: dict) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    if cookies:
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_header.encode()))
    scope = {
        "type": "http",
        "method": method,
        "path": "/",
        "headers": raw_headers,
    }
    return Request(scope)


def test_verify_csrf_allows_safe_methods_with_no_token() -> None:
    request = _make_request("GET", cookies={}, headers={})
    verify_csrf(request)  # must not raise


def test_verify_csrf_rejects_missing_header() -> None:
    request = _make_request("POST", cookies={"csrf_token": "secret"}, headers={})
    with pytest.raises(HTTPException) as exc_info:
        verify_csrf(request)
    assert exc_info.value.status_code == 403


def test_verify_csrf_rejects_mismatched_header() -> None:
    request = _make_request(
        "POST",
        cookies={"csrf_token": "secret"},
        headers={"X-CSRF-Token": "not-the-secret"},
    )
    with pytest.raises(HTTPException):
        verify_csrf(request)


def test_verify_csrf_accepts_matching_cookie_and_header() -> None:
    request = _make_request(
        "POST",
        cookies={"csrf_token": "secret"},
        headers={"X-CSRF-Token": "secret"},
    )
    verify_csrf(request)  # must not raise
