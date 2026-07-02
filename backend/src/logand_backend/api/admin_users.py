from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.users import User
from logand_backend.domain.users.service import (
    admin_reset_password,
    deactivate_customer,
    get_customer,
    reactivate_customer,
)

router = APIRouter(prefix="/api/admin/customers", tags=["admin", "users"])


class ResetPasswordInput(BaseModel):
    model_config = {}

    new_password: str


def _customer_detail(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "emails_opted_out": user.emails_opted_out,
        "disabled_at": user.disabled_at.isoformat() if user.disabled_at else None,
        "created_at": user.created_at.isoformat(),
    }


@router.get("")
async def list_customers(
    q: str | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Customer accounts, id + email only -- what the admin create-invoice
    form needs to let an admin pick who to bill without already knowing
    their UUID. Deliberately never includes password_hash or any other
    User field; this is a lookup list, not a user-management endpoint
    (there is no create/edit/delete-user surface at all yet).

    `q`, when given, filters to emails containing it (case-insensitive
    substring, not a prefix match -- an admin remembering "the gmail
    customer" should still find them). Plain ILIKE, not the inventory
    module's Postgres full-text search (docs/design/06): email is a
    single short field with no natural "relevance ranking" question,
    and a growing customer list is nowhere near the row count where
    ILIKE without an index starts to matter. Always capped at 50 rows --
    a picker dropdown; see get_customer_detail below and
    domain/users/service.py for the real account-management surface.
    """
    stmt = select(User).where(User.role == "customer")
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    stmt = stmt.order_by(User.email).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": str(u.id), "email": u.email} for u in rows]


@router.get("/{user_id}")
async def get_customer_detail(
    user_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await get_customer(db, user_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return _customer_detail(result.danger_ok)


@router.post("/{user_id}/deactivate")
async def deactivate(
    user_id: UUID,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """The frontend is expected to show a real confirmation (this account
    will no longer be able to log in) before calling this -- same
    site-wide "confirmations on everything" convention as inventory's
    /adjust route."""
    result = await deactivate_customer(db, user_id, admin.user_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "deactivated"}


@router.post("/{user_id}/reactivate")
async def reactivate(
    user_id: UUID,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await reactivate_customer(db, user_id, admin.user_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "reactivated"}


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: UUID,
    body: ResetPasswordInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await admin_reset_password(db, user_id, body.new_password, admin.user_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "reset"}
