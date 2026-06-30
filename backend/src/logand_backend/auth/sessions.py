from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Result

from logand_backend.db.base import get_db
from logand_backend.errors import AuthError

_CUSTOMER_IDLE_TIMEOUT = timedelta(minutes=30)
_ADMIN_IDLE_TIMEOUT = timedelta(hours=12)
_ABSOLUTE_MAX_LIFETIME = timedelta(days=7)
_COOKIE_NAME = "__Host-session"


class SessionInfo(BaseModel):
    model_config = {}

    id: UUID
    user_id: UUID
    role: str
    csrf_secret: str
    expires_at: datetime


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


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
    raise NotImplementedError("insert Session row keyed on _hash_token(raw_token); needs db.models.sessions")


async def validate_session(
    db: AsyncSession, raw_token: str
) -> Result[SessionInfo, AuthError]:
    token_hash = _hash_token(raw_token)
    raise NotImplementedError(
        "look up Session by token_hash, check expires_at, slide expiry by "
        "_idle_timeout_for(role) capped at _ABSOLUTE_MAX_LIFETIME from created_at; "
        "needs db.models.sessions"
    )


async def revoke_session(db: AsyncSession, session_id: UUID) -> Result[None, AuthError]:
    raise NotImplementedError("delete Session row by id; needs db.models.sessions")


async def revoke_all_sessions(db: AsyncSession, user_id: UUID) -> Result[None, AuthError]:
    """The admin 'kill all sessions' nuclear option -- deletes every session in
    the table for this user, including the caller's own (docs/design/02)."""
    raise NotImplementedError("delete all Session rows for user_id; needs db.models.sessions")


async def _get_session_from_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> SessionInfo:
    # NOTE: dependencies raise HTTPException directly (401) rather than going
    # through api/errors.py's to_http_exception -- that mapping is for
    # Result[..] returned by domain calls inside a route body, not for
    # auth dependencies that run before the route body executes.
    if session_token is None:
        raise HTTPException(status_code=401, detail=AuthError.SessionNotFound.value)
    result = await validate_session(db, session_token)
    if result.is_err:
        raise HTTPException(status_code=401, detail=result.err.value)
    return result.ok


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
