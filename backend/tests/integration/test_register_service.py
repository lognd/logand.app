from __future__ import annotations

from logand_backend.domain.auth.email_verification import verify_email
from logand_backend.domain.auth.service import get_or_create_contact_user, register
from logand_backend.errors import AuthError


async def test_register_creates_contact_row_and_mints_verify_token(
    db_session,
) -> None:
    """FINDINGS H1: register() no longer writes a password on any branch. A
    freshly registered row is a contact (password_hash NULL, email_verified_at
    NULL) until somebody proves inbox control by redeeming the verify token.
    """
    result = await register(db_session, "new@example.com")

    assert result.is_ok
    user, raw_token = result.danger_ok
    assert raw_token
    assert user.role == "customer"
    assert user.password_hash is None
    assert user.email_verified_at is None


async def test_register_with_active_email_fails(db_session, make_user) -> None:
    user = await make_user(role="customer", password="whatever")

    result = await register(db_session, user.email)

    assert result.is_err
    assert result.danger_err == AuthError.EmailAlreadyRegistered


async def test_register_over_unverified_row_leaves_password_untouched(
    db_session, make_user
) -> None:
    """FINDINGS H1: registering against an unverified row re-mints a verify
    token but NEVER rewrites password_hash -- so re-registration (whether by
    the real owner or an attacker squatting the address) can never plant a
    credential that a later verification click would activate.
    """
    user = await make_user(role="customer", password="first-password", verified=False)
    original_hash = user.password_hash

    result = await register(db_session, user.email)

    assert result.is_ok
    returned_user, raw_token = result.danger_ok
    assert returned_user.id == user.id
    assert returned_user.password_hash == original_hash
    assert raw_token


async def test_register_over_contact_row_is_allowed_and_sets_no_password(
    db_session,
) -> None:
    """docs/design/17: an admin invoicing a bare email leaves a contact
    row (password_hash NULL); registering against it is allowed and keeps
    it a contact -- the password is chosen only at verify time."""
    contact = await get_or_create_contact_user(db_session, "contact@example.com")
    assert contact.password_hash is None

    result = await register(db_session, "contact@example.com")

    assert result.is_ok
    user, raw_token = result.danger_ok
    assert user.id == contact.id
    assert user.password_hash is None
    assert raw_token


async def test_register_email_comparison_is_case_insensitive(db_session) -> None:
    """The second registration attempt for the SAME (still-unverified)
    address is allowed, per docs/design/17. Case-insensitivity is what's
    under test: verifying the FIRST attempt (which chooses the password)
    promotes the row to active, and only THEN does a third attempt with
    different casing correctly fail.
    """
    first = await register(db_session, "Person@Example.com")
    assert first.is_ok
    user, raw_token = first.danger_ok
    assert user.email == "person@example.com"

    verified = await verify_email(db_session, raw_token, "a-real-password")
    assert verified.is_ok

    second = await register(db_session, "person@example.com")
    assert second.is_err
    assert second.danger_err == AuthError.EmailAlreadyRegistered


async def test_register_never_creates_an_admin_account(db_session) -> None:
    # register() takes no role argument at all -- this test exists to make
    # the invariant explicit and to fail loudly if a future change ever
    # threads a role-like parameter through.
    result = await register(db_session, "definitely-customer@example.com")

    assert result.is_ok
    user, _ = result.danger_ok
    assert user.role == "customer"
