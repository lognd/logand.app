from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.csrf import CSRF_COOKIE_NAME
from logand_backend.auth.rate_limit import LOGIN, REGISTER, rate_limit
from logand_backend.auth.sessions import (
    SESSION_COOKIE_NAME,
    SessionInfo,
    _get_session_from_cookie,
)
from logand_backend.db.base import get_db
from logand_backend.domain.auth.service import login as login_domain
from logand_backend.domain.auth.service import logout as logout_domain
from logand_backend.domain.auth.service import register as register_domain

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = {}

    email: str
    password: str


class RegisterRequest(BaseModel):
    model_config = {}

    email: str
    # NOTE: per docs/design/02 -- "no password length cap below 128 chars,
    # no composition rules" for hashed-and-stored passwords in general, but
    # self-registration (unlike admin-created accounts) accepts arbitrary
    # client input, so a minimum length is a real, not theoretical, weakness
    # to close here specifically.
    password: str = Field(min_length=8, max_length=128)


def _set_session_cookies(response: Response, raw_token: str, csrf_secret: str) -> None:
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
        csrf_secret,
        httponly=False,
        secure=True,
        samesite="strict",
        path="/",
    )


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
    _set_session_cookies(response, raw_token, session.csrf_secret)
    return {"status": "ok"}


@router.post("/register")
async def register(
    payload: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("register", *REGISTER)),
) -> dict[str, str]:
    # NOTE: register_domain hardcodes role="customer" -- there is no field
    # on RegisterRequest that can influence the created account's role, by
    # design (see domain/auth/service.py's register() docstring).
    result = await register_domain(db, payload.email, payload.password)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    raw_token, session = result.danger_ok
    _set_session_cookies(response, raw_token, session.csrf_secret)
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
