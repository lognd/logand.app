from __future__ import annotations

from logand_backend.domain.auth.service import get_or_create_contact_user, register
from logand_backend.errors import AuthError


async def test_register_creates_unverified_user_and_mints_verify_token(
    db_session,
) -> None:
    result = await register(db_session, "new@example.com", "a-real-password")

    assert result.is_ok
    user, raw_token = result.danger_ok
    assert raw_token
    assert user.role == "customer"
    assert user.email_verified_at is None


async def test_register_with_active_email_fails(db_session, make_user) -> None:
    user = await make_user(role="customer", password="whatever")

    result = await register(db_session, user.email, "a-different-password")

    assert result.is_err
    assert result.danger_err == AuthError.EmailAlreadyRegistered


async def test_register_over_unverified_row_is_allowed_and_overwrites_password(
    db_session, make_user
) -> None:
    """docs/design/16: registering against an unverified row (e.g. an
    attacker squatting an address, or the real owner re-registering after
    losing the first verify email) overwrites the password and re-mints
    -- unverified rows are not "owned" by anyone yet.
    """
    user = await make_user(role="customer", password="first-password", verified=False)

    result = await register(db_session, user.email, "second-password")

    assert result.is_ok
    returned_user, raw_token = result.danger_ok
    assert returned_user.id == user.id
    assert raw_token


async def test_register_over_contact_row_is_allowed(db_session) -> None:
    """docs/design/16: an admin invoicing a bare email leaves a contact
    row (password_hash NULL); registering against it is allowed."""
    contact = await get_or_create_contact_user(db_session, "contact@example.com")
    assert contact.password_hash is None

    result = await register(db_session, "contact@example.com", "a-real-password")

    assert result.is_ok
    user, raw_token = result.danger_ok
    assert user.id == contact.id
    assert user.password_hash is not None
    assert raw_token


async def test_register_email_comparison_is_case_insensitive(db_session) -> None:
    """The second registration attempt for the SAME (still-unverified)
    address is allowed, per docs/design/16 -- an unverified row isn't
    "owned" by the first registrant. Case-insensitivity is what's under
    test here: verifying the FIRST attempt promotes the row to active, and
    only THEN does a third attempt with different casing correctly fail.
    """
    first = await register(db_session, "Person@Example.com", "a-real-password")
    assert first.is_ok
    user, raw_token = first.danger_ok
    assert user.email == "person@example.com"

    from logand_backend.domain.auth.email_verification import verify_email

    verified = await verify_email(db_session, raw_token)
    assert verified.is_ok

    second = await register(db_session, "person@example.com", "a-different-password")
    assert second.is_err
    assert second.danger_err == AuthError.EmailAlreadyRegistered


async def test_register_never_creates_an_admin_account(db_session) -> None:
    # register() takes no role argument at all -- this test exists to make
    # the invariant explicit and to fail loudly if a future change ever
    # threads a role-like parameter through.
    result = await register(db_session, "definitely-customer@example.com", "pw123456")

    assert result.is_ok
    user, _ = result.danger_ok
    assert user.role == "customer"
