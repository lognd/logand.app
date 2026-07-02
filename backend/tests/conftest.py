from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Iterator
from typing import Awaitable, Callable
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def _isolated_local_storage_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """AppConfig.storage_local_dir defaults to "./data/storage" (relative
    to wherever the process is run from) -- without this, every test that
    exercises a route writing real evidence/receipt/document bytes
    (domain/storage/local.py) would litter backend/data/ in the repo
    working directory instead of a real, auto-cleaned tmp dir. Autouse so
    no test has to remember to opt in.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        monkeypatch.setenv("STORAGE_LOCAL_DIR", tmp_dir)
        yield


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


_INVENTORY_FTS_DDL = """
ALTER TABLE inventory_items
  ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (
    to_tsvector('english', name || ' ' || coalesce(description, ''))
  ) STORED;
CREATE INDEX ix_inventory_items_search_vector
  ON inventory_items USING gin (search_vector);
"""


@pytest_asyncio.fixture
async def db_engine(postgres_url: str) -> AsyncIterator:
    # NOTE: creates tables directly from the ORM metadata rather than running
    # Alembic migrations -- there's no initial migration yet (only the
    # standalone inventory-FTS one, see db/migrations/versions/0001_*.py),
    # so this is the pragmatic path until `alembic revision --autogenerate`
    # has been run once against a real DB. Re-point this at `alembic upgrade
    # head` once an initial migration exists.
    #
    # The generated `search_vector` column from that migration isn't part
    # of the ORM metadata (see db/models/inventory.py's NOTE), so it won't
    # exist after create_all alone -- _INVENTORY_FTS_DDL applies the same
    # DDL that migration's upgrade() would, by hand, so free-text search has
    # real test coverage too instead of being silently skipped.
    import logand_backend.db.base as db_base
    import logand_backend.db.models  # noqa: F401  -- populates Base.metadata
    from logand_backend.db.base import Base

    # NOTE: function-scoped, but postgres_url's container is session-scoped
    # -- drop_all first so each test starts from a clean schema instead of
    # accumulating data (or re-running the non-idempotent FTS DDL below)
    # against tables left over from a previous test.
    engine = db_base.init_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        for statement in _INVENTORY_FTS_DDL.strip().split(";\n"):
            if statement.strip():
                await conn.exec_driver_sql(statement)

    yield engine

    await db_base.dispose_engine()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator:
    import logand_backend.db.base as db_base

    async with db_base._sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # NOTE: base_url is https:// (not http://) even though ASGITransport never
    # touches real TLS -- login sets cookies with Secure=True (see
    # api/auth.py), and httpx's cookie jar follows real browser semantics:
    # a Secure cookie set on one response is silently dropped on the next
    # request if the client base_url scheme is http. Without this, a test
    # that logs in then calls an authenticated endpoint would 401 even with
    # everything else working correctly.
    from logand_backend.app.app import App
    from logand_backend.app.config import AppConfig

    app = App(AppConfig())()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_client(db_engine) -> AsyncIterator[AsyncClient]:
    """Like `client`, but backed by a real Postgres via `db_engine` -- use
    this for any system test that exercises a route touching the DB (auth,
    invoices, budget, inventory). `db_engine` already calls init_engine(),
    so api.db.base.get_db works without dependency_overrides; ASGITransport
    doesn't run FastAPI's lifespan, so we deliberately never call it here.
    """
    from logand_backend.app.app import App
    from logand_backend.app.config import AppConfig

    app = App(AppConfig())()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac


@pytest_asyncio.fixture
def make_user(
    db_session: AsyncSession,
) -> Callable[..., Awaitable["object"]]:
    """Factory fixture: `await make_user(role="customer", password="x")`
    inserts and commits a real users row (FK target for sessions/invoices)
    and returns it. Centralized here since most integration/system tests
    need at least one real user to satisfy FK constraints.

    NOTE: commits, not just flushes -- system tests (db_client fixture)
    open a *separate* DB session per HTTP request via get_db(), which is a
    different transaction than this fixture's db_session. A flush alone is
    only visible within the same transaction; without a commit, the user
    row is invisible to the request's session under read-committed
    isolation, and login would 401 even with the right password.
    """
    from logand_backend.auth.passwords import hash_password
    from logand_backend.db.models.users import User

    async def _make_user(
        role: str = "customer", password: str = "correct horse battery staple"
    ) -> User:
        user = User(
            id=uuid4(),
            email=f"{uuid4()}@example.com",
            password_hash=hash_password(password),
            role=role,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make_user


@pytest_asyncio.fixture
def login_as() -> Callable[..., Awaitable[None]]:
    """`await login_as(db_client, user.email, "pw")` -- POSTs to
    /api/auth/login and asserts success.

    NOTE: the login-route rate limiter (auth/rate_limit.py's RateLimiter) is
    a module-level singleton created once at import time, shared across the
    *entire* pytest process, keyed by client IP -- which ASGITransport fakes
    as a constant value, so every test's login calls would otherwise share
    one rate-limit bucket and spuriously 429 each other out. Spoof a unique
    X-Forwarded-For per call (client_key() in rate_limit.py prefers that
    header) so unrelated tests don't share state. Tests that specifically
    want shared-bucket behavior (the rate-limit test itself) should call the
    raw endpoint directly instead of using this helper.
    """

    async def _login_as(db_client: AsyncClient, email: str, password: str) -> None:
        resp = await db_client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
            headers={"X-Forwarded-For": str(uuid4())},
        )
        assert resp.status_code == 200, resp.text

    return _login_as
