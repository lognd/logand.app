from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from logand_backend.auth.sessions import SessionInfo, _get_session_from_cookie

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    model_config = {}

    status: str = "ok"


class MeResponse(BaseModel):
    model_config = {}

    user_id: str
    role: str


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/api/me")
async def me(session: SessionInfo = Depends(_get_session_from_cookie)) -> MeResponse:
    return MeResponse(user_id=str(session.user_id), role=session.role)
