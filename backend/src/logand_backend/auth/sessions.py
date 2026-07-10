from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.auth.tokens import hash_token
from logand_backend.db.base import get_db
from logand_backend.db.models.sessions import Session
from logand_backend.db.models.users import User
from logand_backend.errors import AuthError

_CUSTOMER_IDLE_TIMEOUT = timedelta(minutes=30)
_ADMIN_IDLE_TIMEOUT = timedelta(hours=12)
_ABSOLUTE_MAX_LIFETIME = timedelta(days=7)
SESSION_COOKIE_NAME = "__Host-session"


class SessionInfo(BaseModel):
    model_config = {}

    id: UUID
    user_id: UUID
    role: str
    csrf_secret: str
    expires_at: datetime


def _idle_timeout_for(role: str) -> timedelta:
    return _ADMIN_IDLE_TIMEOUT if role == "admin" else _CUSTOMER_IDLE_TIMEOUT


async def create_session(
    db: AsyncSession, user_id: UUID, role: str
) -> Result[tuple[str, SessionInfo], AuthError]:
    """Returns (raw_token, SessionInfo). raw_token is set on the cookie and
    never persisted -- only its sha256 (token_hash) is stored, per
    docs/design/02 (a DB leak alone must not let an attacker replay sessions).
    """
    raw_token = secrets.token_urlsafe(32)
    csrf_secret = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = min(now + _idle_timeout_for(role), now + _ABSOLUTE_MAX_LIFETIME)

    row = Session(
        user_id=user_id,
        token_hash=hash_token(raw_token),
        csrf_secret=csrf_secret,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()

    info = SessionInfo(
        id=row.id,
        user_id=row.user_id,
        role=role,
        csrf_secret=row.csrf_secret,
        expires_at=row.expires_at,
    )
    return Ok((raw_token, info))


async def validate_session(
    db: AsyncSession, raw_token: str
) -> Result[SessionInfo, AuthError]:
    token_hash = hash_token(raw_token)

    result = await db.execute(
        select(Session, User.role, User.disabled_at, User.email_verified_at)
        .join(User, User.id == Session.user_id)
        .where(Session.token_hash == token_hash)
    )
    row = result.first()
    if row is None:
        return Err(AuthError.SessionNotFound)

    session_row, role, disabled_at, email_verified_at = row
    now = datetime.now(timezone.utc)
    if session_row.expires_at <= now:
        return Err(AuthError.SessionExpired)
    # Defense in depth: domain/users/service.py's deactivate_customer
    # already revokes every session row outright the moment an account is
    # disabled, so this should never actually find a live session for a
    # disabled user in practice -- but a disabled account's session
    # surviving here (a bug in that revoke call, a direct DB edit via
    # admin_data, a future code path that sets disabled_at without going
    # through deactivate_customer) must still be rejected here too, not
    # silently honored just because the row itself hasn't expired yet.
    if disabled_at is not None:
        return Err(AuthError.SessionNotFound)
    # Same defense-in-depth reasoning, for docs/design/17's load-bearing
    # invariant: login() refuses to create a session for an unverified
    # account, so this should never find a live session for one in
    # practice -- but if one somehow exists (a direct DB edit via
    # admin_data unsetting email_verified_at after the fact, a future
    # bug), every customer-facing invoice read path is gated on this
    # session being valid, so it must be rejected here too, not just at
    # the login boundary.
    if email_verified_at is None:
        return Err(AuthError.SessionNotFound)

    # Slide the idle-timeout window forward, still capped by the absolute
    # max lifetime measured from created_at (per docs/design/02).
    created_at = session_row.created_at
    absolute_cap = created_at + _ABSOLUTE_MAX_LIFETIME
    session_row.expires_at = min(now + _idle_timeout_for(role), absolute_cap)
    await db.flush()

    return Ok(
        SessionInfo(
            id=session_row.id,
            user_id=session_row.user_id,
            role=role,
            csrf_secret=session_row.csrf_secret,
            expires_at=session_row.expires_at,
        )
    )


async def revoke_session(db: AsyncSession, session_id: UUID) -> Result[None, AuthError]:
    # NOTE: AsyncSession.execute() is typed to return the generic
    # sqlalchemy.Result, which doesn't expose .rowcount -- it's only present
    # on CursorResult, which is what a DELETE Core statement actually
    # returns at runtime. Cast to match reality.
    result = cast(
        CursorResult, await db.execute(delete(Session).where(Session.id == session_id))
    )
    if result.rowcount == 0:
        return Err(AuthError.SessionNotFound)
    return Ok(None)


async def revoke_all_sessions_for_user(
    db: AsyncSession, user_id: UUID
) -> Result[None, AuthError]:
    await db.execute(delete(Session).where(Session.user_id == user_id))
    return Ok(None)


async def revoke_all_sessions_globally(db: AsyncSession) -> Result[None, AuthError]:
    """The admin 'kill all sessions' nuclear option -- deletes every session in
    the table, including the caller's own (docs/design/02)."""
    await db.execute(delete(Session))
    return Ok(None)


async def _get_session_from_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> SessionInfo:
    # NOTE: dependencies raise HTTPException directly (401) rather than going
    # through api/errors.py's to_http_exception -- that mapping is for
    # Result[..] returned by domain calls inside a route body, not for
    # auth dependencies that run before the route body executes.
    # app.py's CSRF middleware already ran validate_session for this same
    # token, once, ahead of every non-exempt route (see M1) -- reuse that
    # result instead of running the same session-by-token-hash query
    # again here.
    cached = getattr(request.state, "session_info", None)
    if cached is not None:
        return cached
    if session_token is None:
        raise HTTPException(status_code=401, detail=AuthError.SessionNotFound.value)
    result = await validate_session(db, session_token)
    if result.is_err:
        raise HTTPException(status_code=401, detail=result.danger_err.value)
    return result.danger_ok


async def require_admin(
    session: SessionInfo = Depends(_get_session_from_cookie),
) -> SessionInfo:
    if session.role != "admin":
        raise HTTPException(status_code=401, detail=AuthError.SessionNotFound.value)
    return session


async def require_customer(
    session: SessionInfo = Depends(_get_session_from_cookie),
) -> SessionInfo:
    # NOTE: admin is intentionally NOT allowed through require_customer --
    # "absolute power" means admin bypasses permission checks, it does not
    # mean admin silently impersonates a customer's data scope.
    if session.role != "customer":
        raise HTTPException(status_code=401, detail=AuthError.SessionNotFound.value)
    return session
