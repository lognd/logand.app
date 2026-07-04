from __future__ import annotations

import argparse

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.app.config import AppConfig
from logand_backend.auth.csrf import CSRF_COOKIE_NAME
from logand_backend.auth.rate_limit import (
    LOGIN,
    PASSWORD_RESET_CONFIRM,
    PASSWORD_RESET_REQUEST,
    REGISTER,
    rate_limit,
)
from logand_backend.auth.sessions import (
    SESSION_COOKIE_NAME,
    SessionInfo,
    _get_session_from_cookie,
)
from logand_backend.db.base import get_db
from logand_backend.domain.auth.password_reset import (
    request_password_reset,
)
from logand_backend.domain.auth.password_reset import (
    reset_password as reset_password_domain,
)
from logand_backend.domain.auth.service import login as login_domain
from logand_backend.domain.auth.service import logout as logout_domain
from logand_backend.domain.auth.service import register as register_domain
from logand_backend.domain.notifications.notify import notify_password_reset_requested

router = APIRouter(prefix="/api/auth", tags=["auth"])

# NOTE: rate_limit()'s RateLimiter is constructed once here at import time
# (it backs a Depends(...) default, evaluated when this module loads, not
# per-request), so redis_url has to come from config here too -- previously
# neither login nor register ever passed redis_url at all, so both ALWAYS
# used RateLimiter's in-process dict regardless of whether REDIS_URL was
# configured, silently contradicting docs/design/11's "the redis service is
# mandatory [in production]": rate limits weren't actually shared across
# uvicorn workers or surviving restarts in any real deployment.
# AppConfig.redis_url defaults to None (not a hardcoded-looking-real URL --
# see its own doc comment), so this is a genuine no-op in dev/test where
# REDIS_URL is unset, and only takes effect where it's actually configured
# and reachable (docker-compose.yml/docker-compose.test.yml). RateLimiter
# itself falls back to in-process limiting if Redis turns out to be
# unreachable at request time, so a Redis outage degrades rather than 500s.
_cfg = AppConfig.from_external(argparse.Namespace())


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


class PasswordResetRequestInput(BaseModel):
    model_config = {}

    email: str


class PasswordResetConfirmInput(BaseModel):
    model_config = {}

    token: str
    # Same length rule as RegisterRequest.password (docs/design/02) --
    # this is the one other path (besides self-registration) where a
    # client controls the raw password value end to end.
    new_password: str = Field(min_length=8, max_length=128)


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
    _rate_limit: None = Depends(rate_limit("login", *LOGIN, redis_url=_cfg.redis_url)),
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
    _rate_limit: None = Depends(
        rate_limit("register", *REGISTER, redis_url=_cfg.redis_url)
    ),
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


_PASSWORD_RESET_REQUESTED_MESSAGE = (
    "If an account exists for that email, a password reset link has been sent."
)


@router.post("/password-reset/request")
async def request_password_reset_route(
    payload: PasswordResetRequestInput,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(
        rate_limit(
            "password_reset_request", *PASSWORD_RESET_REQUEST, redis_url=_cfg.redis_url
        )
    ),
) -> dict[str, str]:
    """ALWAYS returns the same 200 body regardless of whether the email
    matches a real account -- see domain.auth.password_reset's own doc
    comment on why letting that vary would turn this into an account-
    enumeration oracle. The actual email send only happens when a real
    account was found; both branches converge on the identical response
    below.

    Critically, the send itself is handed off to `background_tasks`
    rather than awaited here (see FINDINGS.md M1): awaiting a real SMTP/
    OAuth2 send in the request path made real-account responses take
    materially longer than unknown-account ones, a measurable timing
    oracle even though the response body/status were already identical.
    Scheduling it as a background task means this route returns as soon
    as the (cheap, DB-only) token issuance is done either way, so the
    response latency stops depending on whether mail actually gets sent.
    The token row is committed explicitly before scheduling the send (see
    FINDINGS.md L1) so a reset link can never be emailed out for a token
    that a later commit failure rolls back.

    Builds its own `cfg` fresh here (NOT the module-level `_cfg` above,
    which is only for the rate-limiter's `Depends` default -- see this
    module's own top-of-file NOTE) so a test that monkeypatches SMTP_HOST/
    etc. at request time is actually honored, same as every route in
    api/invoices.py.
    """
    cfg = AppConfig.from_external(argparse.Namespace())
    result = await request_password_reset(db, payload.email)
    if result is not None:
        user, raw_token = result
        # Commit now so the token row is durable before we ever schedule
        # the email that carries it -- get_db()'s teardown commit runs
        # AFTER this function returns, i.e. after the background task
        # could already have fired.
        await db.commit()
        reset_url = f"{cfg.public_base_url}/reset-password?token={raw_token}"
        background_tasks.add_task(
            notify_password_reset_requested,
            cfg,
            to_email=user.email,
            to_user_id=user.id,
            reset_url=reset_url,
        )
    return {"status": "ok", "detail": _PASSWORD_RESET_REQUESTED_MESSAGE}


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    payload: PasswordResetConfirmInput,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(
        rate_limit(
            "password_reset_confirm", *PASSWORD_RESET_CONFIRM, redis_url=_cfg.redis_url
        )
    ),
) -> dict[str, str]:
    result = await reset_password_domain(db, payload.token, payload.new_password)
    if result.is_err:
        raise to_http_exception(result.danger_err)
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
    # secure/samesite/httponly must match _set_session_cookies' attributes
    # (see FINDINGS.md L3) -- __Host- prefixed cookies in particular
    # REQUIRE Secure on every Set-Cookie, including the expiry one
    # delete_cookie emits; without it browsers ignore the deletion
    # entirely and the stale cookie lingers.
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", httponly=True, secure=True, samesite="strict"
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME, path="/", httponly=False, secure=True, samesite="strict"
    )
    return {"status": "ok"}
