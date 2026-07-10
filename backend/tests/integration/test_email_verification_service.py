from __future__ import annotations

from datetime import datetime, timedelta, timezone

from logand_backend.auth.tokens import hash_token
from logand_backend.db.models.email_verification_tokens import EmailVerificationToken
from logand_backend.domain.auth.email_verification import (
    claim_invoices,
    get_claim_preview,
    mint_email_verification_token,
    request_verification_resend,
    verify_email,
)
from logand_backend.errors import AuthError


async def test_verify_email_sets_email_verified_at(db_session, make_user) -> None:
    user = await make_user(role="customer", verified=False)
    raw_token = await mint_email_verification_token(db_session, user.id, "verify")

    result = await verify_email(db_session, raw_token)

    assert result.is_ok
    assert result.danger_ok.email_verified_at is not None


async def test_verify_email_rejects_unknown_token(db_session) -> None:
    result = await verify_email(db_session, "not-a-real-token")
    assert result.is_err
    assert result.danger_err == AuthError.EmailVerificationTokenInvalid


async def test_verify_email_rejects_already_used_token(db_session, make_user) -> None:
    user = await make_user(role="customer", verified=False)
    raw_token = await mint_email_verification_token(db_session, user.id, "verify")

    first = await verify_email(db_session, raw_token)
    assert first.is_ok

    second = await verify_email(db_session, raw_token)
    assert second.is_err
    assert second.danger_err == AuthError.EmailVerificationTokenInvalid


async def test_verify_email_rejects_expired_token(db_session, make_user) -> None:
    user = await make_user(role="customer", verified=False)
    raw_token = "a-raw-token-for-this-test-only"
    db_session.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            purpose="verify",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    await db_session.flush()

    result = await verify_email(db_session, raw_token)
    assert result.is_err
    assert result.danger_err == AuthError.EmailVerificationTokenInvalid


async def test_verify_purpose_token_cannot_be_redeemed_as_claim(
    db_session, make_user
) -> None:
    """One table, one code path, purpose discriminates -- a 'verify' token
    must never redeem through the 'claim' path or vice versa.
    """
    user = await make_user(role="customer", verified=False)
    raw_token = await mint_email_verification_token(db_session, user.id, "verify")

    result = await claim_invoices(db_session, raw_token, "brand-new-password-456")
    assert result.is_err
    assert result.danger_err == AuthError.EmailVerificationTokenInvalid


async def test_mint_invalidates_previous_live_token_of_same_purpose(
    db_session, make_user
) -> None:
    user = await make_user(role="customer", verified=False)
    first_token = await mint_email_verification_token(db_session, user.id, "verify")
    second_token = await mint_email_verification_token(db_session, user.id, "verify")

    first_result = await verify_email(db_session, first_token)
    assert first_result.is_err
    assert first_result.danger_err == AuthError.EmailVerificationTokenInvalid

    second_result = await verify_email(db_session, second_token)
    assert second_result.is_ok


async def test_claim_invoices_sets_password_and_verified_at(
    db_session, make_user
) -> None:
    from logand_backend.domain.auth.service import get_or_create_contact_user

    contact = await get_or_create_contact_user(db_session, "contact@example.com")
    raw_token = await mint_email_verification_token(db_session, contact.id, "claim")

    result = await claim_invoices(db_session, raw_token, "brand-new-password-456")

    assert result.is_ok
    claimed = result.danger_ok
    assert claimed.password_hash is not None
    assert claimed.email_verified_at is not None


async def test_claim_invoices_rejects_short_password(db_session) -> None:
    from logand_backend.domain.auth.service import get_or_create_contact_user

    contact = await get_or_create_contact_user(db_session, "contact2@example.com")
    raw_token = await mint_email_verification_token(db_session, contact.id, "claim")

    result = await claim_invoices(db_session, raw_token, "short")

    assert result.is_err
    assert result.danger_err == AuthError.PasswordInvalidLength


async def test_claim_invoices_rejects_already_used_token(db_session) -> None:
    from logand_backend.domain.auth.service import get_or_create_contact_user

    contact = await get_or_create_contact_user(db_session, "contact3@example.com")
    raw_token = await mint_email_verification_token(db_session, contact.id, "claim")

    first = await claim_invoices(db_session, raw_token, "brand-new-password-456")
    assert first.is_ok

    second = await claim_invoices(db_session, raw_token, "another-password-789")
    assert second.is_err
    assert second.danger_err == AuthError.EmailVerificationTokenInvalid


async def test_get_claim_preview_does_not_consume_the_token(
    db_session, make_user
) -> None:
    from logand_backend.domain.auth.service import get_or_create_contact_user

    contact = await get_or_create_contact_user(db_session, "contact4@example.com")
    raw_token = await mint_email_verification_token(db_session, contact.id, "claim")

    preview = await get_claim_preview(db_session, raw_token)
    assert preview.is_ok
    email, invoices = preview.danger_ok
    assert email == "contact4@example.com"
    assert invoices == []

    # Still usable afterward -- the preview must not have spent it.
    result = await claim_invoices(db_session, raw_token, "brand-new-password-456")
    assert result.is_ok


async def test_get_claim_preview_rejects_unknown_token(db_session) -> None:
    result = await get_claim_preview(db_session, "not-a-real-token")
    assert result.is_err
    assert result.danger_err == AuthError.EmailVerificationTokenInvalid


async def test_request_verification_resend_returns_none_for_unknown_email(
    db_session,
) -> None:
    result = await request_verification_resend(db_session, "nobody@example.com")
    assert result is None


async def test_request_verification_resend_returns_none_for_active_account(
    db_session, make_user
) -> None:
    user = await make_user(role="customer", email="active@example.com")
    result = await request_verification_resend(db_session, user.email)
    assert result is None


async def test_request_verification_resend_returns_none_for_contact_row(
    db_session,
) -> None:
    from logand_backend.domain.auth.service import get_or_create_contact_user

    await get_or_create_contact_user(db_session, "just-a-contact@example.com")
    result = await request_verification_resend(db_session, "just-a-contact@example.com")
    assert result is None


async def test_request_verification_resend_mints_for_unverified_account(
    db_session, make_user
) -> None:
    user = await make_user(
        role="customer", email="unverified@example.com", verified=False
    )
    result = await request_verification_resend(db_session, user.email)

    assert result is not None
    returned_user, raw_token = result
    assert returned_user.id == user.id
    assert raw_token

    verified = await verify_email(db_session, raw_token)
    assert verified.is_ok
