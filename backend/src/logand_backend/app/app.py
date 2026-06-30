from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from logand_backend.app.config import AppConfig
from logand_backend.db.base import dispose_engine, init_engine
from logand_backend.logging import get_logger

_log = get_logger(__name__)


class App:
    """Owns the FastAPI instance, lifespan, and router mounting.

    Usage (see __main__.py): `App(cfg)()` returns a built FastAPI app handed
    to uvicorn; the App instance itself is not the ASGI app.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def __call__(self) -> FastAPI:
        app = FastAPI(title="logand.app backend", lifespan=self._lifespan)
        self._mount_routers(app)
        return app

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
