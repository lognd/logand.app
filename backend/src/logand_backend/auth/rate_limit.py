from __future__ import annotations

import time
from typing import cast

import redis.asyncio as redis
from fastapi import HTTPException, Request

# Thresholds per docs/design/02-auth-and-security.md.
LOGIN = (5, 15 * 60)
CUSTOMER_PAY = (20, 60)
GENERAL_AUTHENTICATED = (120, 60)
ADMIN = (300, 60)
PUBLIC = (60, 60)


class RateLimiter:
    """Token-bucket limiter keyed by (bucket_name, client_key).

    NOTE (known v1 limitation, flagged explicitly in docs/design/02): without
    REDIS_URL configured this falls back to an in-process dict, which resets
    on restart and does not share state across uvicorn workers. Fine for a
    single-worker dev box, not a substitute for Redis in production -- see
    docs/design/11-deployment.md, the redis service is mandatory there.
    """

    def __init__(
        self, limit: int, window_seconds: int, redis_url: str | None = None
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._redis_url = redis_url
        self._redis: redis.Redis | None = None
        self._local_buckets: dict[str, list[float]] = {}

    async def check(self, bucket: str, client_key: str) -> None:
        if self._redis_url is not None:
            await self._check_redis(bucket, client_key)
            return
        now = time.monotonic()
        key = f"{bucket}:{client_key}"
        hits = [t for t in self._local_buckets.get(key, []) if now - t < self._window]
        if len(hits) >= self._limit:
            retry_after = int(self._window - (now - hits[0]))
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": str(max(retry_after, 1))},
            )
        hits.append(now)
        self._local_buckets[key] = hits

    async def _check_redis(self, bucket: str, client_key: str) -> None:
        # NOTE: only called from check() when self._redis_url is not None --
        # asserting here narrows the type for the from_url() call below.
        assert self._redis_url is not None
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url)

        key = f"ratelimit:{bucket}:{client_key}"
        # NOTE: INCR + EXPIRE NX is a fixed-window counter, not a true sliding
        # token bucket -- it can allow up to 2x the limit at window boundaries.
        # Acceptable for this site's traffic per docs/design/02; switch to a
        # Lua sliding-window script if that imprecision ever matters.
        # NOTE: redis-py's stubs declare `int | Awaitable[int]` (shared
        # between the sync and async clients), so `ty` sees a non-awaitable
        # branch even though redis.asyncio.Redis.incr always returns an
        # awaitable at runtime. Known redis-py stub looseness, not a real bug.
        count = cast(int, await self._redis.incr(key))  # ty: ignore[invalid-await]
        if count == 1:
            await self._redis.expire(key, self._window)
        if count > self._limit:
            ttl = await self._redis.ttl(key)
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": str(max(ttl, 1))},
            )


def rate_limit(
    bucket: str, limit: int, window_seconds: int, redis_url: str | None = None
):
    """FastAPI dependency factory: `Depends(rate_limit("login", *LOGIN))`."""
    limiter = RateLimiter(limit, window_seconds, redis_url)

    async def _dependency(request: Request) -> None:
        await limiter.check(bucket, client_key(request))

    return _dependency


def client_key(request: Request) -> str:
    # NOTE: trusts X-Forwarded-For only because Caddy (docs/design/11) is the
    # sole entrypoint and sets it -- do not trust this header if the app is
    # ever exposed directly without a reverse proxy in front of it.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
