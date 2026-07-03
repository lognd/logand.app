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


def test_verify_csrf_accepts_matching_pair_bound_to_session_secret() -> None:
    request = _make_request(
        "POST",
        cookies={"csrf_token": "the-real-session-secret"},
        headers={"X-CSRF-Token": "the-real-session-secret"},
    )
    verify_csrf(request, expected_secret="the-real-session-secret")  # must not raise


def test_verify_csrf_rejects_matching_pair_that_is_not_the_session_secret() -> None:
    """Regression test for L1: pure double-submit (cookie==header) is not
    enough -- a stale csrf_token cookie value (left over from a previous
    session/logout, or one an attacker with any first-party write access
    could plant) that happens to match itself as both cookie and header
    must still be rejected once app.py's middleware has resolved the
    CURRENT session's real csrf_secret to compare against.
    """
    request = _make_request(
        "POST",
        cookies={"csrf_token": "stale-or-planted-value"},
        headers={"X-CSRF-Token": "stale-or-planted-value"},
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_csrf(request, expected_secret="the-real-session-secret")
    assert exc_info.value.status_code == 403


def test_verify_csrf_falls_back_to_pure_double_submit_with_no_expected_secret() -> None:
    """expected_secret=None (no live session resolved -- e.g. no session
    cookie at all) must still enforce plain double-submit, not become a
    no-op.
    """
    request = _make_request(
        "POST",
        cookies={"csrf_token": "secret"},
        headers={"X-CSRF-Token": "secret"},
    )
    verify_csrf(request, expected_secret=None)  # must not raise

    mismatched = _make_request(
        "POST",
        cookies={"csrf_token": "secret"},
        headers={"X-CSRF-Token": "different"},
    )
    with pytest.raises(HTTPException):
        verify_csrf(mismatched, expected_secret=None)
