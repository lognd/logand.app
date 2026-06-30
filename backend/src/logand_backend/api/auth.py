from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.csrf import CSRF_COOKIE_NAME
from logand_backend.auth.rate_limit import LOGIN, rate_limit
from logand_backend.auth.sessions import (
    SESSION_COOKIE_NAME,
    SessionInfo,
    _get_session_from_cookie,
)
from logand_backend.db.base import get_db
from logand_backend.domain.auth.service import login as login_domain
from logand_backend.domain.auth.service import logout as logout_domain

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = {}

    email: str
    password: str


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("login", *LOGIN)),
) -> dict[str, str]:
    result = await login_domain(db, payload.email, payload.password)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    raw_token, session = result.danger_ok
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        session.csrf_secret,
        httponly=False,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"status": "ok"}


@router.post("/logout")
async def logout(
    response: Response,
    session: SessionInfo = Depends(_get_session_from_cookie),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await logout_domain(db, session.id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"status": "ok"}
