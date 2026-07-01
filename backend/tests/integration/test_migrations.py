"""Migration round-trip test, per docs/design/12-testing-strategy.md's
explicit requirement (03-database.md): "migration up/down round-trips
cleanly on a fresh DB -- integration, run in CI on every PR that touches a
migration."

This is deliberately independent of conftest.py's db_engine fixture, which
creates its schema from `Base.metadata.create_all()` rather than running
real Alembic migrations (see that fixture's own NOTE) -- every other
integration/system test exercises app code against a schema built that
way, which is fine for testing app code, but it means NOTHING in the rest
of the suite would ever catch a broken migration chain. That gap was real:
`alembic upgrade head` against a genuinely empty database failed outright
before this test existed, because the only migration on disk
(0001_inventory_fts) assumed the ORM's tables already existed (it only
ever ran `ALTER TABLE inventory_items ADD COLUMN ...`) -- there was no
earlier migration that actually created them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# Every table a fresh `alembic upgrade head` must produce -- kept as an
# explicit list (not "whatever Base.metadata currently has") so this test
# fails loudly if a new db/models/*.py table is added without a migration
# for it, not just silently passing because autogenerate would agree with
# itself.
_EXPECTED_TABLES = {
    "users",
    "sessions",
    "invoices",
    "invoice_line_items",
    "payments",
    "budget_entries",
    "budget_entry_evidence",
    "inventory_locations",
    "inventory_items",
    "alembic_version",
}


def _alembic_config() -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        str(_BACKEND_ROOT / "src" / "logand_backend" / "db" / "migrations"),
    )
    return cfg


async def _run_upgrade(cfg: Config, revision: str) -> None:
    # env.py's run_migrations_online() itself calls asyncio.run(...) --
    # command.upgrade()/downgrade() are otherwise-synchronous alembic APIs
    # that end up invoking that internally. Calling them directly from this
    # (already async, pytest-asyncio) test would raise "asyncio.run()
    # cannot be called from a running event loop"; running them in a
    # separate thread gives env.py's asyncio.run() its own fresh loop.
    await asyncio.to_thread(command.upgrade, cfg, revision)


async def _run_downgrade(cfg: Config, revision: str) -> None:
    await asyncio.to_thread(command.downgrade, cfg, revision)


async def _table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        return set(
            await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        )


async def test_alembic_upgrade_head_from_empty_database(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # env.py reads DATABASE_URL directly from os.environ (never from the
    # Alembic Config object), and expects the same asyncpg-flavored URL
    # every other fixture in this suite uses.
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    cfg = _alembic_config()

    # postgres_url's container is session-scoped and shared with every
    # other test that uses db_engine (whose schema comes from
    # Base.metadata.create_all(), not migrations, and isn't guaranteed to
    # be torn down before this test runs -- test execution order isn't
    # guaranteed). Force a genuinely empty schema first regardless of
    # what any earlier test in the session left behind, rather than
    # assuming "head" starts from nothing.
    reset_engine = create_async_engine(postgres_url)
    try:
        async with reset_engine.begin() as conn:
            await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            await conn.exec_driver_sql("CREATE SCHEMA public")
    finally:
        await reset_engine.dispose()

    await _run_upgrade(cfg, "head")

    engine = create_async_engine(postgres_url)
    try:
        tables = await _table_names(engine)
        missing = _EXPECTED_TABLES - tables
        assert not missing, f"alembic upgrade head did not create: {missing}"
    finally:
        await engine.dispose()

    # Round-trip: downgrading all the way back to base must succeed
    # cleanly and leave no domain tables behind.
    await _run_downgrade(cfg, "base")

    engine = create_async_engine(postgres_url)
    try:
        tables = await _table_names(engine)
        leftover = (_EXPECTED_TABLES - {"alembic_version"}) & tables
        assert not leftover, f"alembic downgrade base left tables behind: {leftover}"
    finally:
        await engine.dispose()

    # And re-upgrading from that clean-downgrade state must work again --
    # catches a downgrade() that drops something upgrade() can't recreate.
    await _run_upgrade(cfg, "head")
    engine = create_async_engine(postgres_url)
    try:
        tables = await _table_names(engine)
        missing = _EXPECTED_TABLES - tables
        assert not missing, f"re-running upgrade head after downgrade missed: {missing}"
    finally:
        await engine.dispose()
