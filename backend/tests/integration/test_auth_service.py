from __future__ import annotations

from logand_backend.domain.auth.service import login
from logand_backend.domain.users.service import deactivate_customer
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


async def test_login_fails_for_deactivated_account_same_error_as_wrong_password(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    user = await make_user(role="customer", password="the-real-password")
    await deactivate_customer(db_session, user.id, admin.id)

    result = await login(db_session, user.email, "the-real-password")

    assert result.is_err
    # Same InvalidCredentials as wrong-password/nonexistent-email above --
    # "disabled" must never be a distinguishable error, or it becomes an
    # account-enumeration side channel (see login()'s own doc comment).
    assert result.danger_err == AuthError.InvalidCredentials
