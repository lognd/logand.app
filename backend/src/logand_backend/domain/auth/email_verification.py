from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.auth.passwords import hash_password
from logand_backend.auth.tokens import hash_token
from logand_backend.db.models.email_verification_tokens import EmailVerificationToken
from logand_backend.db.models.invoices import Invoice
from logand_backend.db.models.users import User
from logand_backend.errors import AuthError
from logand_backend.logging import get_logger

_log = get_logger(__name__)

TokenPurpose = Literal["verify", "claim"]

# 'verify' (docs/design/17): short, since register() just sent it and the
# registrant is expected to click through promptly -- same window as
# domain/auth/password_reset.py's own reset-link TTL reasoning.
_VERIFY_TOKEN_TTL = timedelta(hours=24)
# 'claim' gets a much longer TTL than 'verify' -- an invoice email may sit
# unread in an inbox for weeks before the recipient gets around to it, and
# unlike 'verify' there is no self-serve "resend" for a claim link (it's
# re-minted only the next time an admin sends another invoice to that
# contact row).
_CLAIM_TOKEN_TTL = timedelta(days=30)

# Mirrors password_reset.py's own duplicated bound -- see that module's
# doc comment for why this is a defense-in-depth backstop, not the
# primary enforcement point (pydantic's Field(min_length=8, max_length=128)
# on api/auth.py's ClaimConfirmInput is).
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 128


def _ttl_for(purpose: TokenPurpose) -> timedelta:
    return _VERIFY_TOKEN_TTL if purpose == "verify" else _CLAIM_TOKEN_TTL


async def mint_email_verification_token(
    db: AsyncSession, user_id: UUID, purpose: TokenPurpose
) -> str:
    """Invalidates any still-live tokens of the SAME purpose for this user
    (mirrors request_password_reset's own invalidate-then-issue pattern)
    before minting a fresh one, then returns the raw token for the caller
    to email out. Only the sha256 (token_hash) is ever persisted -- see
    auth/tokens.py::hash_token.
    """
    now = datetime.now(timezone.utc)
    await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.purpose == purpose,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
        .values(used_at=now)
    )

    raw_token = secrets.token_urlsafe(32)
    db.add(
        EmailVerificationToken(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            purpose=purpose,
            expires_at=now + _ttl_for(purpose),
        )
    )
    await db.flush()
    _log.info(
        "email verification token issued",
        extra={"user_id": str(user_id), "purpose": purpose},
    )
    return raw_token


async def _redeem_token(
    db: AsyncSession, raw_token: str, purpose: TokenPurpose
) -> Result[User, AuthError]:
    """Shared claim step for both purposes: a single atomic conditional
    UPDATE (WHERE used_at IS NULL AND expires_at > now, RETURNING
    user_id), same reasoning as password_reset.py::reset_password -- under
    READ COMMITTED, a SELECT-then-UPDATE would let two concurrent
    redemptions of the same token both pass validation before either
    writes used_at.
    """
    token_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)
    claimed_user_id = (
        await db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.token_hash == token_hash,
                EmailVerificationToken.purpose == purpose,
                EmailVerificationToken.used_at.is_(None),
                EmailVerificationToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(EmailVerificationToken.user_id)
        )
    ).scalar_one_or_none()
    if claimed_user_id is None:
        _log.warning(
            "email verification token invalid, expired, or already used",
            extra={"purpose": purpose},
        )
        return Err(AuthError.EmailVerificationTokenInvalid)

    user = await db.get(User, claimed_user_id)
    if user is None:
        _log.warning(
            "email verification token redeemed for missing account",
            extra={"user_id": str(claimed_user_id), "purpose": purpose},
        )
        return Err(AuthError.EmailVerificationTokenInvalid)
    return Ok(user)


async def request_verification_resend(
    db: AsyncSession, email: str
) -> tuple[User, str] | None:
    """Mirrors domain/auth/password_reset.py::request_password_reset's own
    no-oracle contract (docs/design/17) -- returns None for "nothing to
    resend" (unknown email, a contact row that never registered, or an
    already-verified/active row), and the caller (api/auth.py) MUST
    respond identically either way so this can't be used to probe which
    addresses have a pending registration.
    """
    normalized_email = email.strip().lower()
    user = (
        await db.execute(
            select(User)
            .where(func.lower(User.email) == normalized_email)
            .order_by(User.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    # Only an "unverified" row (has a password, not yet verified) has
    # anything to resend -- a contact row never registered in the first
    # place (nothing to verify) and an already-verified/active row has
    # nothing left to do.
    if user is None or user.password_hash is None or user.email_verified_at is not None:
        _log.info(
            "verification resend requested for unknown/contact/verified account",
            extra={"email": email},
        )
        return None

    raw_token = await mint_email_verification_token(db, user.id, "verify")
    return user, raw_token


async def verify_email(db: AsyncSession, raw_token: str) -> Result[User, AuthError]:
    """Redeems a 'verify' token: sets email_verified_at. Does not touch
    password_hash -- register() already set it when the row moved from
    contact/unverified to unverified/re-registered.
    """
    result = await _redeem_token(db, raw_token, "verify")
    if result.is_err:
        return result
    user = result.danger_ok
    user.email_verified_at = datetime.now(timezone.utc)
    await db.flush()
    _log.info("email verified", extra={"user_id": str(user.id)})
    return Ok(user)


class ClaimPreviewInvoice:
    """Just enough to show "here's what you're claiming" on the GET
    /api/auth/claim page before a password is set -- never the full
    line-item breakdown (that's still gated behind email_verified_at IS
    NOT NULL once the row becomes active, per docs/design/17's load-
    bearing invariant; this preview is the one deliberate, narrow
    exception, and it only ever reveals what a 'claim' token already
    proves the holder is entitled to see).
    """

    def __init__(self, invoice: Invoice) -> None:
        self.id = invoice.id
        self.status = invoice.status
        self.amount_total = invoice.amount_total
        self.currency = invoice.currency
        self.due_date = invoice.due_date


async def get_claim_preview(
    db: AsyncSession, raw_token: str
) -> Result[tuple[str, list[ClaimPreviewInvoice]], AuthError]:
    """Read-only lookup for GET /api/auth/claim (docs/design/17) -- does
    NOT redeem the token (no used_at write): a customer previewing the
    link before deciding on a password must not burn their one-time
    token just by loading the page.
    """
    token_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)
    token = (
        await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash == token_hash,
                EmailVerificationToken.purpose == "claim",
                EmailVerificationToken.used_at.is_(None),
                EmailVerificationToken.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if token is None:
        return Err(AuthError.EmailVerificationTokenInvalid)

    user = await db.get(User, token.user_id)
    if user is None:
        return Err(AuthError.EmailVerificationTokenInvalid)

    invoices = (
        (
            await db.execute(
                select(Invoice).where(
                    Invoice.customer_id == user.id, Invoice.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    return Ok((user.email, [ClaimPreviewInvoice(i) for i in invoices]))


async def claim_invoices(
    db: AsyncSession, raw_token: str, password: str
) -> Result[User, AuthError]:
    """Redeems a 'claim' token: sets password_hash AND email_verified_at
    in one transaction -- clicking the link *is* the proof of inbox
    control (docs/design/17), so a claim never needs a second
    verification round-trip the way self-registration does.
    """
    if not (_MIN_PASSWORD_LENGTH <= len(password) <= _MAX_PASSWORD_LENGTH):
        _log.warning("invoice claim rejected: password fails length bound")
        return Err(AuthError.PasswordInvalidLength)

    result = await _redeem_token(db, raw_token, "claim")
    if result.is_err:
        return result
    user = result.danger_ok
    user.password_hash = hash_password(password)
    user.email_verified_at = datetime.now(timezone.utc)
    await db.flush()
    _log.info("invoices claimed", extra={"user_id": str(user.id)})
    return Ok(user)
