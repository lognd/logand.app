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

    with PostgresContainer("postgres:16") as pg:
        yield pg.get_connection_url().replace("postgresql://", "postgresql+asyncpg://")


@pytest_asyncio.fixture
async def db_session(postgres_url: str):
    # NOTE: depends on db.base.init_engine + alembic migrations being runnable
    # against a fresh container -- wire this up once db/models/ and the
    # alembic env exist. Left as a fixture stub other test files can import.
    raise NotImplementedError("init_engine(postgres_url), run alembic upgrade head, yield AsyncSession")


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from logand_backend.app.app import App
    from logand_backend.app.config import AppConfig

    app = App(AppConfig())()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
