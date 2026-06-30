from __future__ import annotations

import time

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

    def __init__(self, limit: int, window_seconds: int, redis_url: str | None = None) -> None:
        self._limit = limit
        self._window = window_seconds
        self._redis_url = redis_url
        self._local_buckets: dict[str, list[float]] = {}

    async def check(self, bucket: str, client_key: str) -> None:
        if self._redis_url is not None:
            raise NotImplementedError("redis.asyncio token-bucket check, see redis_url")
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


def client_key(request: Request) -> str:
    # NOTE: trusts X-Forwarded-For only because Caddy (docs/design/11) is the
    # sole entrypoint and sets it -- do not trust this header if the app is
    # ever exposed directly without a reverse proxy in front of it.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
