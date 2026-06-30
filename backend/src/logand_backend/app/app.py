from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from logand_backend.app.config import AppConfig
from logand_backend.db.base import dispose_engine, init_engine
from logand_backend.logging import get_logger

_log = get_logger(__name__)

# Routes exempt from the CSRF double-submit check in _csrf_middleware:
# - /api/auth/login: no session cookie exists yet to carry a CSRF secret.
# - /api/webhooks/*: authenticated by Stripe signature verification instead
#   (see api/webhooks.py), a browser-originated cookie/header pair is never
#   present on a server-to-server webhook call.
_CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login"})
_CSRF_EXEMPT_PREFIXES = ("/api/webhooks",)


class App:
    """Owns the FastAPI instance, lifespan, and router mounting.

    Usage (see __main__.py): `App(cfg)()` returns a built FastAPI app handed
    to uvicorn; the App instance itself is not the ASGI app.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def __call__(self) -> FastAPI:
        app = FastAPI(title="logand.app backend", lifespan=self._lifespan)
        app.middleware("http")(self._csrf_middleware)
        self._mount_routers(app)
        return app

    async def _csrf_middleware(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # NOTE: verify_csrf is a plain function (not a FastAPI Depends) so it
        # can run here, once, ahead of every router, rather than needing to
        # be added to each mutating route individually -- see
        # docs/design/02-auth-and-security.md's double-submit CSRF section.
        # NOTE: HTTPException raised inside @app.middleware("http") is NOT
        # caught by Starlette's ExceptionMiddleware (that middleware wraps
        # the *router*, not custom ASGI middleware added this way) -- left
        # unhandled it would surface as a 500, not the intended 403. Catch
        # and convert explicitly.
        from logand_backend.auth.csrf import verify_csrf

        path = request.url.path
        if path not in _CSRF_EXEMPT_PATHS and not path.startswith(
            _CSRF_EXEMPT_PREFIXES
        ):
            try:
                verify_csrf(request)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code, content={"detail": exc.detail}
                )
        return await call_next(request)

    def _mount_routers(self, app: FastAPI) -> None:
        # NOTE: deferred imports -- routers pull in domain/db modules we don't
        # want loaded just to construct an App for, e.g., a unit test that
        # never calls __call__.
        from logand_backend.api import (
            auth,
            budget,
            health,
            inventory,
            invoices,
            invoices_public,
            webhooks,
        )

        app.include_router(health.router)
        app.include_router(auth.router)
        app.include_router(invoices.router)
        app.include_router(invoices_public.router)
        app.include_router(budget.router)
        app.include_router(inventory.router)
        app.include_router(webhooks.router)

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        _log.info("starting up: initializing database engine")
        init_engine(self._config.database_url)
        try:
            yield
        finally:
            _log.info("shutting down: disposing database engine")
            await dispose_engine()
