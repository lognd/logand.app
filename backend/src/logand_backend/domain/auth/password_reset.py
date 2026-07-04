from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.auth.passwords import hash_password
from logand_backend.auth.sessions import revoke_all_sessions_for_user
from logand_backend.auth.tokens import hash_token
from logand_backend.db.models.password_reset_tokens import PasswordResetToken
from logand_backend.db.models.users import User
from logand_backend.errors import AuthError
from logand_backend.logging import get_logger

_log = get_logger(__name__)

# Long enough that a real recipient checking email a few minutes later
# isn't rushed, short enough that a stale, forwarded, or archived reset
# email stops being a live credential quickly. Confirm is also its own,
# tighter-rate-limited endpoint (see auth/rate_limit.py), so this isn't
# the only thing standing between a leaked link and account takeover.
_TOKEN_TTL = timedelta(hours=1)

# Mirrors PasswordResetConfirmInput.new_password's Field(min_length=8,
# max_length=128) in api/auth.py (same bound as RegisterRequest.password,
# per docs/design/02) -- duplicated here, not imported, because pydantic
# validation happens a layer above this function and every current caller
# already goes through that model; this is a defense-in-depth backstop for
# any future non-HTTP caller of reset_password() directly, not the
# primary enforcement point.
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 128


async def request_password_reset(
    db: AsyncSession, email: str
) -> tuple[User, str] | None:
    """Looks up `email` (case-insensitively, same normalization as
    domain/auth/service.py::login) and, if a live account exists, creates
    a reset token and returns (user, raw_token) for the caller (the API
    route) to email out.

    Returns None when there's no such account, or it's disabled -- the
    caller MUST respond with the exact same generic message/status
    either way, never letting this function's None-vs-not result leak
    into the HTTP response, or the "forgot password" form becomes an
    account-enumeration oracle (same reasoning as login's own
    AuthError.InvalidCredentials covering both "no such user" and "wrong
    password").
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
    if user is None or user.disabled_at is not None:
        _log.info(
            "password reset requested for unknown or disabled account",
            extra={"email": email},
        )
        return None

    # Invalidate any still-live tokens from earlier requests before
    # issuing a new one (docs/design/02) -- otherwise every unused,
    # unexpired token from prior "forgot password" submissions stays a
    # live credential in parallel with the new one, widening the window
    # any one forwarded/leaked reset email keeps working.
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
        .values(used_at=datetime.now(timezone.utc))
    )

    raw_token = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + _TOKEN_TTL,
        )
    )
    await db.flush()
    _log.info(
        "password reset token issued", extra={"email": email, "user_id": str(user.id)}
    )
    return user, raw_token


async def reset_password(
    db: AsyncSession, raw_token: str, new_password: str
) -> Result[None, AuthError]:
    """Redeems a reset token: sets the new password, marks the token
    used (so it can never be redeemed again even within its TTL), and
    revokes every existing session for the account -- same reasoning as
    domain/users/service.py::admin_reset_password: a password reset is
    frequently a response to a compromised or forgotten credential, so
    any session established under the old password must not survive it.

    The claim itself is a single atomic conditional UPDATE (WHERE
    used_at IS NULL AND expires_at > now, RETURNING user_id) rather than
    a SELECT-then-check-then-UPDATE (docs/design/02): under READ
    COMMITTED, two concurrent confirms with the same token could
    otherwise both read used_at IS NULL before either writes it, both
    pass validation, and both redeem the same single-use token. The
    UPDATE's WHERE clause makes the row-level lock the database takes
    while evaluating it the only thing that decides which (if any)
    concurrent request wins; zero rows updated means the token was
    invalid, expired, or already claimed by another request.
    """
    if not (_MIN_PASSWORD_LENGTH <= len(new_password) <= _MAX_PASSWORD_LENGTH):
        _log.warning("password reset rejected: new password fails length bound")
        return Err(AuthError.PasswordInvalidLength)

    token_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)
    claimed_user_id = (
        await db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(PasswordResetToken.user_id)
        )
    ).scalar_one_or_none()
    if claimed_user_id is None:
        _log.warning("password reset token invalid, expired, or already used")
        return Err(AuthError.PasswordResetTokenInvalid)

    user = await db.get(User, claimed_user_id)
    if user is None or user.disabled_at is not None:
        _log.warning(
            "password reset token redeemed for missing or disabled account",
            extra={"user_id": str(claimed_user_id)},
        )
        return Err(AuthError.PasswordResetTokenInvalid)

    user.password_hash = hash_password(new_password)
    await db.flush()
    await revoke_all_sessions_for_user(db, user.id)
    _log.info("password reset completed", extra={"user_id": str(user.id)})
    return Ok(None)
