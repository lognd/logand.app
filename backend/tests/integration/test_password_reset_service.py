from __future__ import annotations

from datetime import datetime, timedelta, timezone

from logand_backend.auth.sessions import validate_session
from logand_backend.auth.tokens import hash_token
from logand_backend.db.models.password_reset_tokens import PasswordResetToken
from logand_backend.domain.auth.password_reset import (
    request_password_reset,
    reset_password,
)
from logand_backend.domain.auth.service import login
from logand_backend.errors import AuthError


async def test_request_password_reset_returns_none_for_unknown_email(
    db_session,
) -> None:
    result = await request_password_reset(db_session, "nobody@example.com")
    assert result is None


async def test_request_password_reset_returns_user_and_token_for_known_email(
    db_session, make_user
) -> None:
    user = await make_user(role="customer", email="user@example.com")

    result = await request_password_reset(db_session, "user@example.com")

    assert result is not None
    returned_user, raw_token = result
    assert returned_user.id == user.id
    assert len(raw_token) > 20


async def test_request_password_reset_is_case_insensitive(
    db_session, make_user
) -> None:
    await make_user(role="customer", email="user@example.com")
    result = await request_password_reset(db_session, "User@Example.com")
    assert result is not None


async def test_request_password_reset_returns_none_for_disabled_account(
    db_session, make_user
) -> None:
    user = await make_user(role="customer", email="disabled@example.com")
    user.disabled_at = datetime.now(timezone.utc)
    await db_session.flush()

    result = await request_password_reset(db_session, "disabled@example.com")
    assert result is None


async def test_reset_password_updates_password_and_allows_new_login(
    db_session, make_user
) -> None:
    user = await make_user(
        role="customer", email="user@example.com", password="old-password-123"
    )
    _, raw_token = await request_password_reset(db_session, "user@example.com")

    result = await reset_password(db_session, raw_token, "brand-new-password-456")
    assert result.is_ok

    old_login = await login(db_session, "user@example.com", "old-password-123")
    assert old_login.is_err
    assert old_login.danger_err == AuthError.InvalidCredentials

    new_login = await login(db_session, "user@example.com", "brand-new-password-456")
    assert new_login.is_ok
    _, session = new_login.danger_ok
    assert session.user_id == user.id


async def test_reset_password_revokes_existing_sessions(db_session, make_user) -> None:
    await make_user(role="customer", email="user@example.com")
    login_result = await login(
        db_session, "user@example.com", "correct horse battery staple"
    )
    raw_session_token, session = login_result.danger_ok

    _, raw_reset_token = await request_password_reset(db_session, "user@example.com")
    result = await reset_password(db_session, raw_reset_token, "brand-new-password-456")
    assert result.is_ok

    validation = await validate_session(db_session, raw_session_token)
    assert validation.is_err
    assert validation.danger_err == AuthError.SessionNotFound


async def test_reset_password_rejects_unknown_token(db_session) -> None:
    result = await reset_password(
        db_session, "not-a-real-token", "brand-new-password-456"
    )
    assert result.is_err
    assert result.danger_err == AuthError.PasswordResetTokenInvalid


async def test_reset_password_rejects_already_used_token(db_session, make_user) -> None:
    await make_user(role="customer", email="user@example.com")
    _, raw_token = await request_password_reset(db_session, "user@example.com")

    first = await reset_password(db_session, raw_token, "brand-new-password-456")
    assert first.is_ok

    second = await reset_password(db_session, raw_token, "yet-another-password-789")
    assert second.is_err
    assert second.danger_err == AuthError.PasswordResetTokenInvalid


async def test_reset_password_rejects_expired_token(db_session, make_user) -> None:
    user = await make_user(role="customer", email="user@example.com")
    raw_token = "a-raw-token-for-this-test-only"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    await db_session.flush()

    result = await reset_password(db_session, raw_token, "brand-new-password-456")
    assert result.is_err
    assert result.danger_err == AuthError.PasswordResetTokenInvalid
