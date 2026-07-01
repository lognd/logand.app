from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from logand_backend.app.app import App
from logand_backend.app.config import AppConfig
from logand_backend.db.models.users import User


async def test_seeded_admin_can_actually_log_in(db_engine) -> None:
    """Exercises the real runtime path (App._seed_admin_if_configured, not
    just the underlying ensure_admin_seeded domain function directly, see
    tests/integration/test_admin_seed.py for that) -- constructs an App
    with SEED_ADMIN_EMAIL/PASSWORD configured, the same way
    docker-compose.test.yml's backend service is, and confirms the seeded
    account can log in over real HTTP afterward.

    db_engine (not db_client) -- this test needs to call
    _seed_admin_if_configured() directly against an already-initialized
    engine rather than going through ASGITransport, since ASGITransport
    never runs FastAPI's lifespan (see conftest.py's db_client NOTE) --
    the whole point here is confirming what the lifespan actually does.
    """
    config = AppConfig(
        seed_admin_email="lifespan-seeded-admin@example.com",
        seed_admin_password="lifespan-seed-password",
    )
    app_builder = App(config)
    fastapi_app = app_builder()
    await app_builder._seed_admin_if_configured()

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        login_resp = await client.post(
            "/api/auth/login",
            json={
                "email": "lifespan-seeded-admin@example.com",
                "password": "lifespan-seed-password",
            },
            headers={"X-Forwarded-For": "203.0.113.200"},
        )
        assert login_resp.status_code == 200, login_resp.text

        me = await client.get("/api/me")
        assert me.status_code == 200
        assert me.json()["role"] == "admin"


async def test_seed_admin_is_noop_without_both_env_vars(db_engine) -> None:
    config = AppConfig(
        seed_admin_email="only-email-set@example.com", seed_admin_password=None
    )
    app_builder = App(config)
    app_builder()
    await app_builder._seed_admin_if_configured()

    from logand_backend.db.base import _sessionmaker

    async with _sessionmaker() as session:  # type: ignore[misc]
        rows = (
            (
                await session.execute(
                    select(User).where(User.email == "only-email-set@example.com")
                )
            )
            .scalars()
            .all()
        )
    assert rows == []
