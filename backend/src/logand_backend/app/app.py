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
# - /api/auth/login, /api/auth/register: no session cookie exists yet to
#   carry a CSRF secret -- there's nothing to double-submit against.
# - /api/webhooks/*: authenticated by Stripe signature verification instead
#   (see api/webhooks.py), a browser-originated cookie/header pair is never
#   present on a server-to-server webhook call.
# - /api/unsubscribe: authenticated by the signed token in the query string
#   instead (see api/notifications.py) -- both a human clicking a link from
#   an email client and a mail server's own RFC 8058 one-click POST have no
#   session cookie/CSRF token to present at all.
_CSRF_EXEMPT_PATHS = frozenset(
    {"/api/auth/login", "/api/auth/register", "/api/unsubscribe"}
)
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
            admin_users,
            auth,
            budget,
            health,
            inventory,
            invoices,
            invoices_public,
            mileage,
            notifications,
            webhooks,
        )

        app.include_router(health.router)
        app.include_router(auth.router)
        app.include_router(invoices.router)
        app.include_router(invoices_public.router)
        app.include_router(budget.router)
        app.include_router(inventory.router)
        app.include_router(webhooks.router)
        app.include_router(admin_users.router)
        app.include_router(notifications.router)
        app.include_router(mileage.router)

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        _log.info("starting up: initializing database engine")
        init_engine(self._config.database_url)
        await self._seed_admin_if_configured()
        try:
            yield
        finally:
            _log.info("shutting down: disposing database engine")
            await dispose_engine()

    async def _seed_admin_if_configured(self) -> None:
        # Opt-in only (see AppConfig.seed_admin_email/password and
        # domain/auth/service.py's ensure_admin_seeded docstring) --
        # a real production deployment has no reason to keep either env
        # var set past its very first bootstrap, so this is a no-op there.
        # Used by docker-compose.test.yml (CI's system-test stack) and
        # local dev to guarantee a known admin fixture exists without a
        # separate seeding step anyone could forget to run.
        email = self._config.seed_admin_email
        password = self._config.seed_admin_password
        if not email or not password:
            return

        import logand_backend.db.base as db_base
        from logand_backend.domain.auth.service import ensure_admin_seeded

        assert db_base._sessionmaker is not None  # init_engine() just ran above
        async with db_base._sessionmaker() as session:
            await ensure_admin_seeded(session, email, password)
            await session.commit()
        _log.info("seeded admin account", extra={"email": email})
