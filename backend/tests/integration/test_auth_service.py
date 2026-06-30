from __future__ import annotations

from logand_backend.domain.auth.service import login
from logand_backend.errors import AuthError


async def test_login_succeeds_with_correct_password(db_session, make_user) -> None:
    user = await make_user(role="customer", password="the-real-password")

    result = await login(db_session, user.email, "the-real-password")

    assert result.is_ok
    _, session = result.danger_ok
    assert session.user_id == user.id
    assert session.role == "customer"


async def test_login_fails_with_wrong_password(db_session, make_user) -> None:
    user = await make_user(role="customer", password="the-real-password")

    result = await login(db_session, user.email, "not-the-real-password")

    assert result.is_err
    assert result.danger_err == AuthError.InvalidCredentials


async def test_login_fails_for_nonexistent_email_same_error_as_wrong_password(
    db_session,
) -> None:
    result = await login(db_session, "nobody@example.com", "whatever")

    assert result.is_err
    assert result.danger_err == AuthError.InvalidCredentials
