from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Result

from logand_backend.auth.passwords import verify_password
from logand_backend.auth.sessions import SessionInfo, create_session
from logand_backend.errors import AuthError


async def login(db: AsyncSession, email: str, password: str) -> Result[tuple[str, SessionInfo], AuthError]:
    """Looks up the user by email, verifies the password, and on success
    creates a session. Deliberately returns the same AuthError.InvalidCredentials
    for both "no such user" and "wrong password" -- never let the error
    distinguish account existence (standard login-enumeration defense).
    """
    raise NotImplementedError("look up user by email; needs db.models.users")


async def logout(db: AsyncSession, session_id: UUID) -> Result[None, AuthError]:
    from logand_backend.auth.sessions import revoke_session

    return await revoke_session(db, session_id)
