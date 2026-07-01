from __future__ import annotations

import logging
import time
from typing import cast

import redis.asyncio as redis
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Thresholds per docs/design/02-auth-and-security.md.
LOGIN = (5, 15 * 60)
CUSTOMER_PAY = (20, 60)
GENERAL_AUTHENTICATED = (120, 60)
ADMIN = (300, 60)
PUBLIC = (60, 60)
# Self-registration isn't in the original design doc (added later at the
# user's request) -- same threshold as LOGIN. Mass account creation is the
# concrete abuse case (spam/credential-stuffing setup), and registration is
# rarer than login in legitimate use, so LOGIN's 5/15min is tight enough
# without needing its own number to tune independently yet.
REGISTER = LOGIN


class RateLimiter:
    """Token-bucket limiter keyed by (bucket_name, client_key).

    Backed by Redis when `redis_url` is configured (shares state across
    uvicorn workers and survives restarts -- see docs/design/11-deployment.md,
    the redis service is mandatory in production), falling back to an
    in-process dict otherwise (dev/test without REDIS_URL set) OR if Redis
    is configured but turns out to be unreachable at request time -- a
    rate limiter is defense in depth, not core functionality, so an outage
    in the Redis dependency degrades to weaker (per-process) limiting
    rather than 500ing every login/register/payment attempt. Once a Redis
    error is seen, this instance stops retrying it for its own lifetime
    (see _redis_unavailable) rather than eating a fresh connection-timeout
    latency hit on every subsequent request during an outage.
    """

    def __init__(
        self, limit: int, window_seconds: int, redis_url: str | None = None
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._redis_url = redis_url
        self._redis: redis.Redis | None = None
        self._redis_unavailable = False
        self._local_buckets: dict[str, list[float]] = {}

    async def check(self, bucket: str, client_key: str) -> None:
        if self._redis_url is not None and not self._redis_unavailable:
            try:
                await self._check_redis(bucket, client_key)
                return
            except HTTPException:
                raise  # a real 429 from _check_redis, not a connection failure
            except redis.RedisError as exc:
                self._redis_unavailable = True
                logger.warning(
                    "rate limiter: Redis unavailable (%s), falling back to "
                    "in-process limiting for the rest of this process's life",
                    exc,
                )
        self._check_local(bucket, client_key)

    def _check_local(self, bucket: str, client_key: str) -> None:
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
