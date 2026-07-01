from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.users import User

router = APIRouter(prefix="/api/admin/customers", tags=["admin", "users"])


@router.get("")
async def list_customers(
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Every customer account, id + email only -- what the admin
    create-invoice form needs to let an admin pick who to bill without
    already knowing their UUID. Deliberately never includes password_hash
    or any other User field; this is a lookup list, not a user-management
    endpoint (there is no create/edit/delete-user surface at all yet).
    """
    rows = (
        (
            await db.execute(
                select(User).where(User.role == "customer").order_by(User.email)
            )
        )
        .scalars()
        .all()
    )
    return [{"id": str(u.id), "email": u.email} for u in rows]
