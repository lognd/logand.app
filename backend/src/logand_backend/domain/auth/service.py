from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Result

from logand_backend.auth.passwords import verify_password
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


async def logout(db: AsyncSession, session_id: UUID) -> Result[None, AuthError]:
    from logand_backend.auth.sessions import revoke_session

    return await revoke_session(db, session_id)
