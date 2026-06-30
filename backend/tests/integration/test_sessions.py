from __future__ import annotations

from datetime import datetime, timedelta, timezone

from logand_backend.auth.sessions import (
    create_session,
    revoke_all_sessions_for_user,
    revoke_all_sessions_globally,
    revoke_session,
    validate_session,
)
from logand_backend.db.models.sessions import Session


async def test_create_then_validate_session_round_trip(db_session, make_user) -> None:
    user = await make_user(role="customer")

    create_result = await create_session(db_session, user.id, role="customer")
    assert create_result.is_ok
    raw_token, _ = create_result.danger_ok

    validate_result = await validate_session(db_session, raw_token)
    assert validate_result.is_ok
    assert validate_result.danger_ok.user_id == user.id


async def test_revoked_session_no_longer_validates(db_session, make_user) -> None:
    user = await make_user(role="admin")

    create_result = await create_session(db_session, user.id, role="admin")
    raw_token, session = create_result.danger_ok

    await revoke_session(db_session, session.id)
    validate_result = await validate_session(db_session, raw_token)
    assert validate_result.is_err


async def test_unknown_token_fails_to_validate(db_session) -> None:
    result = await validate_session(db_session, "not-a-real-token")
    assert result.is_err


async def test_admin_idle_timeout_is_longer_than_customer(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")

    admin_token, _ = (
        await create_session(db_session, admin.id, role="admin")
    ).danger_ok
    customer_token, _ = (
        await create_session(db_session, customer.id, role="customer")
    ).danger_ok

    admin_session = (await validate_session(db_session, admin_token)).danger_ok
    customer_session = (await validate_session(db_session, customer_token)).danger_ok

    now = datetime.now(timezone.utc)
    admin_remaining = admin_session.expires_at - now
    customer_remaining = customer_session.expires_at - now

    # Admin idle timeout (12h) is far longer than customer's (30min) per
    # docs/design/02 -- generous bounds to avoid timing flakiness.
    assert admin_remaining > timedelta(hours=6)
    assert customer_remaining < timedelta(hours=1)


async def test_session_expiry_is_capped_at_absolute_max_lifetime(
    db_session, make_user
) -> None:
    user = await make_user(role="customer")
    raw_token, info = (
        await create_session(db_session, user.id, role="customer")
    ).danger_ok

    # Backdate created_at to just under the 7-day absolute cap so the next
    # idle-window slide (30min for a customer) would overshoot it.
    row = await db_session.get(Session, info.id)
    row.created_at = datetime.now(timezone.utc) - timedelta(
        days=6, hours=23, minutes=58
    )
    await db_session.flush()

    validate_result = await validate_session(db_session, raw_token)
    assert validate_result.is_ok
    session = validate_result.danger_ok

    absolute_cap = row.created_at + timedelta(days=7)
    assert session.expires_at <= absolute_cap + timedelta(seconds=1)


async def test_revoke_all_sessions_for_user_only_affects_that_user(
    db_session, make_user
) -> None:
    user_a = await make_user(role="customer")
    user_b = await make_user(role="customer")

    token_a, _ = (
        await create_session(db_session, user_a.id, role="customer")
    ).danger_ok
    token_b, _ = (
        await create_session(db_session, user_b.id, role="customer")
    ).danger_ok

    await revoke_all_sessions_for_user(db_session, user_a.id)

    assert (await validate_session(db_session, token_a)).is_err
    assert (await validate_session(db_session, token_b)).is_ok


async def test_revoke_all_sessions_globally_kills_every_session(
    db_session, make_user
) -> None:
    user_a = await make_user(role="customer")
    user_b = await make_user(role="admin")

    token_a, _ = (
        await create_session(db_session, user_a.id, role="customer")
    ).danger_ok
    token_b, _ = (await create_session(db_session, user_b.id, role="admin")).danger_ok

    await revoke_all_sessions_globally(db_session)

    assert (await validate_session(db_session, token_a)).is_err
    assert (await validate_session(db_session, token_b)).is_err
