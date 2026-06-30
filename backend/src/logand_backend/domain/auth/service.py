from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Result

from logand_backend.auth.passwords import hash_password, verify_password
from logand_backend.auth.sessions import SessionInfo, create_session
from logand_backend.db.models.users import User
from logand_backend.errors import AuthError


async def login(
    db: AsyncSession, email: str, password: str
) -> Result[tuple[str, SessionInfo], AuthError]:
    """Looks up the user by email, verifies the password, and on success
    creates a session. Deliberately returns the same AuthError.InvalidCredentials
    for both "no such user" and "wrong password" -- never let the error
    distinguish account existence (standard login-enumeration defense).
    """
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        return Err(AuthError.InvalidCredentials)
    if not verify_password(password, user.password_hash):
        return Err(AuthError.InvalidCredentials)
    return await create_session(db, user.id, user.role)


async def register(
    db: AsyncSession, email: str, password: str
) -> Result[tuple[str, SessionInfo], AuthError]:
    """Self-registration, customer role only -- there is no request path
    that can set role to "admin" here, by design (docs/design/02: exactly
    one admin account ever exists, created out of band, never via this
    endpoint). On success the new user is logged in immediately, returning
    the same (raw_token, SessionInfo) shape as login() so the API layer can
    reuse login's cookie-setting code unchanged.

    Email comparison/storage is lowercased so "User@x.com" and "user@x.com"
    can't both register -- the case-insensitive lookup here is a
    best-effort pre-check; the real guard against a duplicate is the
    `users.email` unique constraint plus the IntegrityError catch below,
    since two concurrent registrations for the same email would otherwise
    both pass this SELECT before either INSERT commits.
    """
    normalized_email = email.strip().lower()

    existing = (
        await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    ).scalar_one_or_none()
    if existing is not None:
        return Err(AuthError.EmailAlreadyRegistered)

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        role="customer",
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        return Err(AuthError.EmailAlreadyRegistered)

    return await create_session(db, user.id, user.role)


async def logout(db: AsyncSession, session_id: UUID) -> Result[None, AuthError]:
    from logand_backend.auth.sessions import revoke_session

    return await revoke_session(db, session_id)
