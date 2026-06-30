from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="session")
async def postgres_url() -> AsyncIterator[str]:
    """Real Postgres via testcontainers, per docs/design/12-testing-strategy.md
    -- integration/system tests never mock the database. Skips cleanly if
    Docker isn't available locally (CI always has it)."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    # NOTE: get_connection_url() defaults to the psycopg2 driver -- request
    # asyncpg explicitly rather than string-replacing, since the default
    # driver string isn't "postgresql://" (it's "postgresql+psycopg2://").
    with PostgresContainer("postgres:16") as pg:
        yield pg.get_connection_url(driver="asyncpg")


@pytest_asyncio.fixture
async def db_session(postgres_url: str) -> AsyncIterator:
    # NOTE: creates tables directly from the ORM metadata rather than running
    # Alembic migrations -- there's no initial migration yet (only the
    # standalone inventory-FTS one, see db/migrations/versions/0001_*.py),
    # so this is the pragmatic path until `alembic revision --autogenerate`
    # has been run once against a real DB. Re-point this at `alembic upgrade
    # head` once an initial migration exists.
    import logand_backend.db.base as db_base
    import logand_backend.db.models  # noqa: F401  -- populates Base.metadata
    from logand_backend.db.base import Base

    engine = db_base.init_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db_base._sessionmaker() as session:
        yield session

    await db_base.dispose_engine()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from logand_backend.app.app import App
    from logand_backend.app.config import AppConfig

    app = App(AppConfig())()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
