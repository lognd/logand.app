from __future__ import annotations

from logand_backend.domain.auth.service import register
from logand_backend.errors import AuthError


async def test_register_creates_customer_and_logs_in(db_session) -> None:
    result = await register(db_session, "new@example.com", "a-real-password")

    assert result.is_ok
    raw_token, session = result.danger_ok
    assert raw_token
    assert session.role == "customer"


async def test_register_with_already_used_email_fails(db_session, make_user) -> None:
    user = await make_user(role="customer", password="whatever")

    result = await register(db_session, user.email, "a-different-password")

    assert result.is_err
    assert result.danger_err == AuthError.EmailAlreadyRegistered


async def test_register_email_comparison_is_case_insensitive(db_session) -> None:
    first = await register(db_session, "Person@Example.com", "a-real-password")
    assert first.is_ok

    second = await register(db_session, "person@example.com", "a-different-password")
    assert second.is_err
    assert second.danger_err == AuthError.EmailAlreadyRegistered


async def test_register_never_creates_an_admin_account(db_session) -> None:
    # register() takes no role argument at all -- this test exists to make
    # the invariant explicit and to fail loudly if a future change ever
    # threads a role-like parameter through.
    result = await register(db_session, "definitely-customer@example.com", "pw123456")

    assert result.is_ok
    _, session = result.danger_ok
    assert session.role == "customer"
