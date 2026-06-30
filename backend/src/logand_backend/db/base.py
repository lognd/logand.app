from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. Every model in db/models/ inherits this."""


# NOTE: engine/sessionmaker are created lazily via init_engine(), not at import
# time -- importing db.base must never require DATABASE_URL to already be set
# (tests construct their own engine against a test database).
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    _engine = create_async_engine(database_url, pool_pre_ping=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency: yields one session per request, rolled back on error."""
    if _sessionmaker is None:
        raise RuntimeError("init_engine() must be called before get_db() is used")
    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
