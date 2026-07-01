from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import redis
from fastapi import HTTPException

from logand_backend.auth.rate_limit import RateLimiter


async def test_in_process_fallback_blocks_after_limit() -> None:
    limiter = RateLimiter(limit=2, window_seconds=60)  # no redis_url -> in-process
    await limiter.check("bucket", "client")
    await limiter.check("bucket", "client")
    with pytest.raises(HTTPException) as exc_info:
        await limiter.check("bucket", "client")
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


async def test_in_process_fallback_keys_are_independent_per_client() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60)
    await limiter.check("bucket", "client-a")
    await limiter.check("bucket", "client-b")  # different client_key, own bucket
    with pytest.raises(HTTPException):
        await limiter.check("bucket", "client-a")


async def test_redis_configured_but_unreachable_falls_back_to_local() -> None:
    """A RateLimiter with redis_url set, but Redis actually unreachable at
    request time, must degrade to in-process limiting rather than raising
    an unhandled error -- rate limiting is defense in depth, not core
    functionality, so an outage in Redis shouldn't take down login/
    register/pay.
    """
    limiter = RateLimiter(
        limit=1, window_seconds=60, redis_url="redis://nonexistent:6379/0"
    )
    with patch.object(
        limiter,
        "_check_redis",
        AsyncMock(side_effect=redis.ConnectionError("connection refused")),
    ):
        # First call: hits the broken Redis path, catches the error, falls
        # back to local -- and since this is the first hit locally, it's
        # allowed through (not rate limited yet).
        await limiter.check("bucket", "client")
    assert limiter._redis_unavailable is True

    # Second call: _check_redis is no longer even attempted (patched away
    # entirely to prove this), pure in-process path, and this is the
    # second hit against a limit of 1 -> blocked.
    with pytest.raises(HTTPException) as exc_info:
        await limiter.check("bucket", "client")
    assert exc_info.value.status_code == 429


async def test_real_429_from_redis_path_is_not_treated_as_connection_failure() -> None:
    """A 429 HTTPException raised by _check_redis (the limit was actually
    exceeded, per Redis's own counter) must propagate as-is -- it must not
    be caught by the same except block that catches Redis connection
    errors and silently swallowed into a fallback-and-allow.
    """
    limiter = RateLimiter(
        limit=1, window_seconds=60, redis_url="redis://nonexistent:6379/0"
    )
    with patch.object(
        limiter,
        "_check_redis",
        AsyncMock(
            side_effect=HTTPException(status_code=429, detail="rate limit exceeded")
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await limiter.check("bucket", "client")
    assert exc_info.value.status_code == 429
    # And Redis is NOT marked unavailable -- it responded correctly, it
    # just said "no."
    assert limiter._redis_unavailable is False
