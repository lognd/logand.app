from __future__ import annotations

from uuid import uuid4

from logand_backend.auth.sessions import (
    create_session,
    revoke_session,
    validate_session,
)
from logand_backend.db.models.users import User


async def _make_user(db_session, role: str) -> User:
    user = User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        password_hash="not-a-real-hash",
        role=role,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_then_validate_session_round_trip(db_session) -> None:
    user = await _make_user(db_session, role="customer")

    create_result = await create_session(db_session, user.id, role="customer")
    assert create_result.is_ok
    raw_token, _ = create_result.ok

    validate_result = await validate_session(db_session, raw_token)
    assert validate_result.is_ok
    assert validate_result.ok.user_id == user.id


async def test_revoked_session_no_longer_validates(db_session) -> None:
    user = await _make_user(db_session, role="admin")

    create_result = await create_session(db_session, user.id, role="admin")
    raw_token, session = create_result.ok

    await revoke_session(db_session, session.id)
    validate_result = await validate_session(db_session, raw_token)
    assert validate_result.is_err
