from __future__ import annotations

import argparse
import html

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.base import get_db
from logand_backend.db.models.users import User
from logand_backend.domain.notifications import mailer

router = APIRouter(prefix="/api/unsubscribe", tags=["notifications"])

_INVALID_TOKEN_DETAIL = "invalid or expired unsubscribe link"


async def _apply_unsubscribe(db: AsyncSession, token: str) -> bool:
    cfg = AppConfig.from_external(argparse.Namespace())
    user_id = mailer.verify_unsubscribe_token(token, cfg)
    if user_id is None:
        return False
    user = await db.get(User, user_id)
    if user is None:
        return False
    user.emails_opted_out = True
    await db.flush()
    return True


@router.get("")
async def unsubscribe_get(token: str) -> HTMLResponse:
    """No auth (like api/webhooks.py's stripe route) by design -- the
    signed token itself is the authorization, exactly what CAN-SPAM's
    "no login required to unsubscribe" expectation calls for. Reached by
    a human clicking the plain-text link in an email footer.

    Deliberately does NOT mutate state (FINDINGS.md L1): the token has no
    expiry/nonce scoping, so an automated GET (corporate link-scanners,
    antivirus link-rewriting, mail-client link preflight/prefetch) would
    silently opt a real customer out with no human intent behind it. This
    only validates the token's signature and renders a confirmation page
    with a POST-back form; the actual `emails_opted_out` write happens
    only on `unsubscribe_post` below, which a scanner's GET can't trigger.
    """
    cfg = AppConfig.from_external(argparse.Namespace())
    if mailer.verify_unsubscribe_token(token, cfg) is None:
        raise HTTPException(status_code=400, detail=_INVALID_TOKEN_DETAIL)
    escaped_token = html.escape(token, quote=True)
    return HTMLResponse(
        "<html><body>"
        "<p>Click below to confirm you want to unsubscribe from these emails.</p>"
        f'<form method="post" action="/api/unsubscribe?token={escaped_token}">'
        '<button type="submit">Unsubscribe</button>'
        "</form>"
        "</body></html>"
    )


@router.post("")
async def unsubscribe_post(
    token: str, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """RFC 8058 one-click target -- mail clients POST here directly (a
    "List-Unsubscribe=One-Click" form body some clients send is
    deliberately not parsed; the token in the query string is the only
    thing this needs). No auth here either, same reasoning as the GET
    route above.
    """
    if not await _apply_unsubscribe(db, token):
        raise HTTPException(status_code=400, detail=_INVALID_TOKEN_DETAIL)
    return {"status": "unsubscribed"}
