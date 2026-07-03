from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from logand_backend.app.config import AppConfig
from logand_backend.db.base import dispose_engine, init_engine
from logand_backend.logging import get_logger
from logand_backend.logging.request_context import new_request_id, set_request_id

_log = get_logger(__name__)
_access_log = get_logger("logand_backend.access")

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
        # Registered AFTER _csrf_middleware -- Starlette's http middleware
        # wraps in reverse registration order, so this one ends up
        # OUTERMOST and its request id is already set (via the contextvar
        # in logging/request_context.py) by the time the CSRF check itself
        # runs and might log something.
        app.middleware("http")(self._request_logging_middleware)
        self._mount_routers(app)
        return app

    async def _request_logging_middleware(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """The single place every request is logged -- "centralized, not
        scattered" per the user's own requirement. One JSON line per
        request (method, path, status, duration_ms, request_id) regardless
        of which router handled it, plus the request id is what ties this
        line to any error/exception lines logged deeper in the call stack
        and to whatever request id a frontend crash report (see
        frontend/src/lib/logging.ts) hands back for correlation.
        """
        # Deliberately NOT cleared in a finally: each request is handled in
        # its own asyncio Task with its own copy of the contextvar context
        # (Starlette/anyio propagate a snapshot per request), so this
        # never leaks into a concurrent request -- and NOT clearing it
        # means _unhandled_exception_handler below still sees the right
        # request id even though ServerErrorMiddleware invokes it further
        # up the stack, after this function's frame would otherwise have
        # already torn down a `finally`-cleared value.
        request_id = request.headers.get("X-Request-Id") or new_request_id()
        set_request_id(request_id)
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            # NOTE: caught HERE, not via app.add_exception_handler(Exception,
            # ...) -- Starlette's BaseHTTPMiddleware (what app.middleware
            # ("http") uses under the hood) has a long-standing limitation
            # where an exception raised past call_next does NOT reach
            # exception handlers registered that way; it just propagates
            # out of the ASGI app entirely. Confirmed against a real test:
            # a registered Exception handler never fired with this
            # middleware present. Catching directly here is what actually
            # converts every unhandled exception to a real 500 response
            # instead of a raw connection failure.
            #
            # Anything reaching here is a genuine bug (an ErrorSet variant
            # never raises a bare Exception -- see api/errors.py's
            # to_http_exception, which is how every EXPECTED domain error
            # already becomes a real HTTPException upstream of this).
            # Full traceback + request id logged server-side; the client
            # gets a generic message, never exc's own text (could leak
            # internals).
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            _log.error(
                "unhandled exception",
                exc_info=exc,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "request_id": request_id,
                },
            )
            response = JSONResponse(
                status_code=500, content={"detail": "internal server error"}
            )
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        level = _access_log.warning if response.status_code >= 500 else _access_log.info
        level(
            "request complete",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "request_id": request_id,
            },
        )
        return response

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
        from logand_backend.auth.csrf import _SAFE_METHODS, verify_csrf
        from logand_backend.auth.sessions import SESSION_COOKIE_NAME, validate_session

        path = request.url.path
        # Boundary-matched (not bare startswith) so a prefix like
        # "/api/webhooks" exempts "/api/webhooks/..." only, never a
        # lookalike path such as "/api/webhooks-foo" that happens to
        # share the same string prefix -- see L2 in FINDINGS.md.
        is_exempt_prefix = any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in _CSRF_EXEMPT_PREFIXES
        )
        if path not in _CSRF_EXEMPT_PATHS and not is_exempt_prefix:
            # Bind the double-submit check to the CURRENT session's own
            # csrf_secret, not just cookie==header -- see verify_csrf's
            # own doc comment for why plain double-submit alone is a
            # weaker guarantee than it looks. This runs the SAME
            # validate_session used by _get_session_from_cookie (rather
            # than a separate read-only peek) and stashes the resolved
            # SessionInfo on request.state -- _get_session_from_cookie
            # below reuses it instead of re-querying, so each request
            # does exactly one session-by-token-hash lookup, not two
            # (see M1).
            expected_secret: str | None = None
            session_token = request.cookies.get(SESSION_COOKIE_NAME)
            # Only resolve (and thereby, on success, slide/commit) the
            # session for a method verify_csrf will actually check below --
            # verify_csrf itself no-ops for _SAFE_METHODS, so doing this for
            # every GET/HEAD/OPTIONS bought nothing but ran validate_session's
            # idle-timeout slide (a write-commit) on every single read
            # request, silently widening the effective idle-timeout
            # window. A safe request still gets its session resolved
            # exactly once, by the route's own auth dependency downstream
            # (_get_session_from_cookie's own validate_session call),
            # same as before this middleware existed.
            if session_token and request.method not in _SAFE_METHODS:
                import logand_backend.db.base as db_base

                if db_base._sessionmaker is not None:
                    async with db_base._sessionmaker() as csrf_db:
                        result = await validate_session(csrf_db, session_token)
                        if result.is_ok:
                            request.state.session_info = result.danger_ok
                            expected_secret = result.danger_ok.csrf_secret
                            # Per L1: don't commit the idle-timeout slide
                            # yet -- a CSRF-failed request must not count
                            # as legitimate session activity. Only commit
                            # once verify_csrf below has actually passed;
                            # if it raises, the transaction is rolled back
                            # on context exit and the slide never persists.
                            try:
                                verify_csrf(request, expected_secret)
                            except HTTPException as exc:
                                await csrf_db.rollback()
                                return JSONResponse(
                                    status_code=exc.status_code,
                                    content={"detail": exc.detail},
                                )
                            await csrf_db.commit()
                            return await call_next(request)
                        elif request.method not in _SAFE_METHODS:
                            # A session cookie is present but unresolvable
                            # (expired/unknown) on a mutating request --
                            # per L1, treat this distinctly from "no
                            # cookie at all" rather than silently
                            # downgrading to a plain double-submit check.
                            # A GET with a stale cookie still falls
                            # through below: the route's own auth
                            # dependency (if any) is what should reject
                            # it, not the CSRF layer.
                            return JSONResponse(
                                status_code=401,
                                content={"detail": result.danger_err.value},
                            )
            try:
                verify_csrf(request, expected_secret)
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
            admin_data,
            admin_logs,
            admin_users,
            admin_version,
            auth,
            bom,
            budget,
            documents,
            health,
            inventory,
            invoices,
            invoices_public,
            mileage,
            notifications,
            receipts,
            webhooks,
        )

        app.include_router(health.router)
        app.include_router(auth.router)
        app.include_router(invoices.router)
        app.include_router(invoices_public.router)
        app.include_router(budget.router)
        app.include_router(inventory.router)
        app.include_router(bom.router)
        app.include_router(webhooks.router)
        app.include_router(admin_users.router)
        app.include_router(notifications.router)
        app.include_router(mileage.router)
        app.include_router(receipts.router)
        app.include_router(documents.router)
        app.include_router(admin_data.router)
        app.include_router(admin_logs.router)
        app.include_router(admin_version.router)

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
