from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

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
async def me() -> MeResponse:
    # NOTE: deliberately not wired to a single Depends() yet -- /api/me needs
    # to accept either an admin or a customer session and return whichever
    # role is present, which require_admin/require_customer (each of which
    # 401s on role mismatch) don't directly support. Real implementation:
    # resolve the raw session via sessions._get_session_from_cookie and
    # branch on .role, rather than depending on both guards.
    raise NotImplementedError("resolve session role-agnostically; see note above")
