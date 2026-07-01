from __future__ import annotations

from sqlalchemy import select

from logand_backend.auth.passwords import verify_password
from logand_backend.db.models.users import User
from logand_backend.domain.auth.service import ensure_admin_seeded


async def test_ensure_admin_seeded_creates_admin_when_absent(db_session) -> None:
    user = await ensure_admin_seeded(
        db_session, "Seed-Admin@Example.com", "seed-password-1"
    )

    assert user.role == "admin"
    # Lowercased, same convention as register() -- so a differently-cased
    # SEED_ADMIN_EMAIL env var on a later restart still matches this row
    # instead of creating a second admin.
    assert user.email == "seed-admin@example.com"
    assert verify_password("seed-password-1", user.password_hash)


async def test_ensure_admin_seeded_is_idempotent(db_session) -> None:
    first = await ensure_admin_seeded(db_session, "admin@example.com", "first-password")
    second = await ensure_admin_seeded(
        db_session, "admin@example.com", "first-password"
    )

    assert first.id == second.id
    rows = (
        (
            await db_session.execute(
                select(User).where(User.email == "admin@example.com")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_ensure_admin_seeded_updates_password_on_rerun(db_session) -> None:
    await ensure_admin_seeded(db_session, "admin@example.com", "old-password")
    updated = await ensure_admin_seeded(db_session, "admin@example.com", "new-password")

    assert verify_password("new-password", updated.password_hash)
    assert not verify_password("old-password", updated.password_hash)


async def test_ensure_admin_seeded_promotes_existing_non_admin_row(
    db_session, make_user
) -> None:
    # Guards against a pre-existing customer row at the same email ever
    # silently staying a customer -- the seed's whole point is guaranteeing
    # an admin account exists at this address.
    existing = await make_user(role="customer", password="whatever")

    seeded = await ensure_admin_seeded(db_session, existing.email, "admin-password")

    assert seeded.id == existing.id
    assert seeded.role == "admin"
