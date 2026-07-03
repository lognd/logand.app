"""Real HTTP client against the real production origin. Wraps httpx so
every probe gets CSRF header attachment and cookie handling for free,
exactly matching what a real browser session does (see
backend/src/logand_backend/auth/csrf.py and api/auth.py's
_set_session_cookies for the contract this mirrors).
"""

from __future__ import annotations

import httpx

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_COOKIE_NAME = "session_token"


class ProdHttpClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ProdHttpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def is_authenticated(self) -> bool:
        return SESSION_COOKIE_NAME in self._client.cookies

    def _csrf_headers(self) -> dict[str, str]:
        token = self._client.cookies.get(CSRF_COOKIE_NAME)
        return {CSRF_HEADER_NAME: token} if token else {}

    def get(self, path: str, **kwargs: object) -> httpx.Response:
        return self._client.get(path, **kwargs)  # type: ignore[arg-type]

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        headers = {**self._csrf_headers(), **kwargs.pop("headers", {})}  # type: ignore[arg-type]
        return self._client.post(path, headers=headers, **kwargs)  # type: ignore[arg-type]

    def patch(self, path: str, **kwargs: object) -> httpx.Response:
        headers = {**self._csrf_headers(), **kwargs.pop("headers", {})}  # type: ignore[arg-type]
        return self._client.patch(path, headers=headers, **kwargs)  # type: ignore[arg-type]

    def delete(self, path: str, **kwargs: object) -> httpx.Response:
        headers = {**self._csrf_headers(), **kwargs.pop("headers", {})}  # type: ignore[arg-type]
        return self._client.delete(path, headers=headers, **kwargs)  # type: ignore[arg-type]

    def login(self, email: str, password: str) -> httpx.Response:
        # Deliberately does NOT clear cookies first -- a probe wanting a
        # fresh unauthenticated client should construct a new
        # ProdHttpClient rather than reuse one that's already logged in as
        # someone else, so cookie state always matches "who does this
        # object claim to be" for the whole object's lifetime.
        return self.post("/api/auth/login", json={"email": email, "password": password})

    def logout(self) -> httpx.Response:
        return self.post("/api/auth/logout")

    def new_unauthenticated(self) -> "ProdHttpClient":
        return ProdHttpClient(str(self._client.base_url))
