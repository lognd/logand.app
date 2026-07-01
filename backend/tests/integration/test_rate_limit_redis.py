"""RateLimiter against a REAL Redis -- tests/unit/test_rate_limit.py covers
the in-process fallback and connection-failure resilience with mocks; this
is the integration-layer counterpart docs/design/12-testing-strategy.md
requires (Redis is a real system this code talks to, not something to
mock in an integration test). Requires REDIS_URL to point at a reachable
Redis; skips cleanly if not configured for this test run (this repo's
plain `uv run pytest` / CI `backend` job don't run one -- only
docker-compose.test.yml's system-tests job does).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi import HTTPException

from logand_backend.auth.rate_limit import RateLimiter

_REDIS_URL = os.environ.get("REDIS_URL")

pytestmark = pytest.mark.skipif(
    _REDIS_URL is None, reason="REDIS_URL not set -- no real Redis to test against"
)


async def test_redis_backed_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter(limit=2, window_seconds=60, redis_url=_REDIS_URL)
    bucket = f"test-{uuid4()}"  # unique per test run, real Redis persists across tests
    await limiter.check(bucket, "client")
    await limiter.check(bucket, "client")
    with pytest.raises(HTTPException) as exc_info:
        await limiter.check(bucket, "client")
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


async def test_redis_backed_limiter_shares_state_across_separate_instances() -> None:
    """The entire point of the Redis backend over the in-process dict:
    two separate RateLimiter objects (standing in for two separate uvicorn
    worker processes) must see the same counter.
    """
    bucket = f"test-{uuid4()}"
    limiter_a = RateLimiter(limit=1, window_seconds=60, redis_url=_REDIS_URL)
    limiter_b = RateLimiter(limit=1, window_seconds=60, redis_url=_REDIS_URL)

    await limiter_a.check(bucket, "client")
    with pytest.raises(HTTPException):
        await limiter_b.check(bucket, "client")


async def test_redis_backed_limiter_keys_are_independent_per_client() -> None:
    bucket = f"test-{uuid4()}"
    limiter = RateLimiter(limit=1, window_seconds=60, redis_url=_REDIS_URL)
    await limiter.check(bucket, "client-a")
    await limiter.check(bucket, "client-b")
    with pytest.raises(HTTPException):
        await limiter.check(bucket, "client-a")
