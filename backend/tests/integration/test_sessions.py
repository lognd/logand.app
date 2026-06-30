from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="needs db.models.sessions + db_session fixture wiring -- fill in once those land")


async def test_create_then_validate_session_round_trip(db_session) -> None:
    from uuid import uuid4

    from logand_backend.auth.sessions import create_session, validate_session

    user_id = uuid4()
    create_result = await create_session(db_session, user_id, role="customer")
    assert create_result.is_ok
    raw_token, _ = create_result.ok

    validate_result = await validate_session(db_session, raw_token)
    assert validate_result.is_ok
    assert validate_result.ok.user_id == user_id


async def test_revoked_session_no_longer_validates(db_session) -> None:
    from uuid import uuid4

    from logand_backend.auth.sessions import create_session, revoke_session, validate_session

    user_id = uuid4()
    create_result = await create_session(db_session, user_id, role="admin")
    raw_token, session = create_result.ok

    await revoke_session(db_session, session.id)
    validate_result = await validate_session(db_session, raw_token)
    assert validate_result.is_err
