from __future__ import annotations

from logand_backend.app.config import AppConfig
from logand_backend.scripts.health_check import check_database, check_storage


async def test_check_database_succeeds_against_a_real_postgres(
    postgres_url: str,
) -> None:
    cfg = AppConfig(database_url=postgres_url)
    assert await check_database(cfg) is True


async def test_check_database_fails_against_an_unreachable_host() -> None:
    cfg = AppConfig(
        database_url="postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere"
    )
    assert await check_database(cfg) is False


async def test_check_storage_round_trips_against_the_local_backend(tmp_path) -> None:
    cfg = AppConfig(storage_backend="local", storage_local_dir=str(tmp_path))
    assert await check_storage(cfg) is True
