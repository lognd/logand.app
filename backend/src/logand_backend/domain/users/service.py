from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.auth.passwords import hash_password
from logand_backend.db.models.audit import AdminAuditLog
from logand_backend.db.models.users import User
from logand_backend.errors import UserError

_MIN_PASSWORD_LENGTH = 8


def _user_snapshot(user: User) -> dict:
    """Never includes password_hash -- see AdminAuditLog's own doc
    comment on why secrets never go into a *_state snapshot. Every other
    field is real, current data, so a revert can genuinely reconstruct
    the account's state (minus the password itself, which is handled by
    its own audit action with no hash captured at all -- see
    admin_reset_password below)."""
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "emails_opted_out": user.emails_opted_out,
        "disabled_at": user.disabled_at.isoformat() if user.disabled_at else None,
    }


async def get_customer(db: AsyncSession, user_id: UUID) -> Result[User, UserError]:
    user = await db.get(User, user_id)
    if user is None:
        return Err(UserError.NotFound)
    if user.role != "customer":
        return Err(UserError.CannotModifyAdmin)
    return Ok(user)


async def deactivate_customer(
    db: AsyncSession, user_id: UUID, admin_id: UUID
) -> Result[UUID, UserError]:
    """Sets disabled_at -- checked at login (domain/auth/service.py), so
    this genuinely blocks authentication, not just hides the account from
    a list somewhere. Writes a full before/after snapshot to
    AdminAuditLog first -- that snapshot IS the rollback record (see
    reactivate_customer, which is the actual "undo").
    """
    result = await get_customer(db, user_id)
    if result.is_err:
        return result
    user = result.danger_ok
    before = _user_snapshot(user)

    user.disabled_at = datetime.now(timezone.utc)
    await db.flush()

    log_id = uuid4()
    db.add(
        AdminAuditLog(
            id=log_id,
            admin_id=admin_id,
            action="user.deactivate",
            target_table="users",
            target_id=str(user_id),
            before_state=before,
            after_state=_user_snapshot(user),
        )
    )
    await db.flush()
    return Ok(log_id)


async def reactivate_customer(
    db: AsyncSession, user_id: UUID, admin_id: UUID
) -> Result[UUID, UserError]:
    result = await get_customer(db, user_id)
    if result.is_err:
        return result
    user = result.danger_ok
    before = _user_snapshot(user)

    user.disabled_at = None
    await db.flush()

    log_id = uuid4()
    db.add(
        AdminAuditLog(
            id=log_id,
            admin_id=admin_id,
            action="user.reactivate",
            target_table="users",
            target_id=str(user_id),
            before_state=before,
            after_state=_user_snapshot(user),
        )
    )
    await db.flush()
    return Ok(log_id)


async def admin_reset_password(
    db: AsyncSession, user_id: UUID, new_password: str, admin_id: UUID
) -> Result[UUID, UserError]:
    """An admin-initiated password reset -- e.g. a customer locked out
    with no working email. The audit entry records THAT a reset
    happened and who did it, never the password itself (not the raw
    value, not the new hash) -- see AdminAuditLog's own doc comment.
    """
    if len(new_password) < _MIN_PASSWORD_LENGTH:
        return Err(UserError.PasswordTooShort)
    result = await get_customer(db, user_id)
    if result.is_err:
        return result
    user = result.danger_ok

    user.password_hash = hash_password(new_password)
    await db.flush()

    log_id = uuid4()
    db.add(
        AdminAuditLog(
            id=log_id,
            admin_id=admin_id,
            action="user.reset_password",
            target_table="users",
            target_id=str(user_id),
            before_state=None,
            after_state=None,
        )
    )
    await db.flush()
    return Ok(log_id)
