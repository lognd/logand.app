from __future__ import annotations

from logand_backend.auth.sessions import create_session, validate_session
from logand_backend.domain.auth.service import login
from logand_backend.domain.users.service import (
    admin_reset_password,
    deactivate_customer,
)
from logand_backend.errors import AuthError


async def test_login_is_case_insensitive_on_email(db_session, make_user) -> None:
    """Regression test for H2: register()/ensure_admin_seeded() both store
    emails lowercased and stripped -- login() must look up the same way,
    or a real user typing their own email back with different casing
    (or a stray leading/trailing space) gets InvalidCredentials despite
    the password being correct.
    """
    user = await make_user(
        role="customer", password="the-real-password", email="user@example.com"
    )

    result = await login(db_session, "User@Example.com", "the-real-password")

    assert result.is_ok
    _, session = result.danger_ok
    assert session.user_id == user.id


async def test_login_strips_whitespace_from_email(db_session, make_user) -> None:
    user = await make_user(
        role="customer", password="the-real-password", email="user@example.com"
    )

    result = await login(db_session, "  user@example.com  ", "the-real-password")

    assert result.is_ok
    _, session = result.danger_ok
    assert session.user_id == user.id


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


async def test_deactivate_customer_revokes_existing_sessions(
    db_session, make_user
) -> None:
    """Regression test for H3: a customer already logged in must be
    logged out IMMEDIATELY on deactivation, not just blocked from a
    future login -- deactivate_customer must revoke every live session
    for that user, not only set disabled_at.
    """
    admin = await make_user(role="admin")
    user = await make_user(role="customer", password="the-real-password")
    raw_token, _ = (await create_session(db_session, user.id, "customer")).danger_ok

    pre_check = await validate_session(db_session, raw_token)
    assert pre_check.is_ok

    result = await deactivate_customer(db_session, user.id, admin.id)
    assert result.is_ok

    post_check = await validate_session(db_session, raw_token)
    assert post_check.is_err
    assert post_check.danger_err == AuthError.SessionNotFound


async def test_admin_reset_password_revokes_existing_sessions(
    db_session, make_user
) -> None:
    """Regression test for L2: a password reset is frequently a response
    to a compromised account -- any session established before the reset
    (by an attacker or the old, possibly-leaked password) must not
    survive it.
    """
    admin = await make_user(role="admin")
    user = await make_user(role="customer", password="old-password")
    raw_token, _ = (await create_session(db_session, user.id, "customer")).danger_ok

    result = await admin_reset_password(
        db_session, user.id, "brand-new-password", admin.id
    )
    assert result.is_ok

    post_check = await validate_session(db_session, raw_token)
    assert post_check.is_err
    assert post_check.danger_err == AuthError.SessionNotFound

    # The new password is genuinely usable afterward -- this isn't just
    # "sessions revoked," the reset itself still worked.
    login_result = await login(db_session, user.email, "brand-new-password")
    assert login_result.is_ok


async def test_validate_session_rejects_session_for_disabled_user(
    db_session, make_user
) -> None:
    """Defense-in-depth regression test for H3: even if a session row
    somehow survives an account being disabled (deactivate_customer's own
    revoke call failing, a direct admin_data edit setting disabled_at
    without going through deactivate_customer), validate_session must
    still refuse it.
    """
    user = await make_user(role="customer", password="the-real-password")
    raw_token, _ = (await create_session(db_session, user.id, "customer")).danger_ok

    from logand_backend.db.models.users import User

    db_user = await db_session.get(User, user.id)
    from datetime import datetime, timezone

    db_user.disabled_at = datetime.now(timezone.utc)
    await db_session.flush()

    result = await validate_session(db_session, raw_token)
    assert result.is_err
    assert result.danger_err == AuthError.SessionNotFound
