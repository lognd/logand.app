from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.audit import AdminAuditLog
from logand_backend.domain.admin_data import service

router = APIRouter(prefix="/api/admin/data", tags=["admin", "data"])


class UpdateRowInput(BaseModel):
    changes: dict


class InsertRowInput(BaseModel):
    values: dict


def _log_summary(log: AdminAuditLog) -> dict:
    return {
        "id": str(log.id),
        "admin_id": str(log.admin_id) if log.admin_id else None,
        "action": log.action,
        "target_table": log.target_table,
        "target_id": log.target_id,
        "before_state": log.before_state,
        "after_state": log.after_state,
        "created_at": log.created_at.isoformat(),
    }


@router.get("/tables")
async def list_tables(
    _admin: SessionInfo = Depends(require_admin),
) -> list[str]:
    return service.list_tables()


@router.get("/tables/{table_name}/schema")
async def get_table_schema(
    table_name: str,
    _admin: SessionInfo = Depends(require_admin),
) -> list[dict]:
    result = service.get_table_columns(table_name)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return result.danger_ok


@router.get("/tables/{table_name}/rows")
async def list_rows(
    table_name: str,
    limit: int = 50,
    offset: int = 0,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await service.list_rows(db, table_name, limit, offset)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return result.danger_ok


@router.get("/tables/{table_name}/rows/{row_id}")
async def get_row(
    table_name: str,
    row_id: str,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await service.get_row(db, table_name, row_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return result.danger_ok


@router.post("/tables/{table_name}/rows")
async def insert_row(
    table_name: str,
    body: InsertRowInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The frontend must show a real before/after (here: no-before, full
    after) confirm step, same site-wide convention as every other risky
    admin action, before ever calling this."""
    result = await service.insert_row(db, table_name, body.values, admin.user_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"change_id": str(result.danger_ok)}


@router.patch("/tables/{table_name}/rows/{row_id}")
async def update_row(
    table_name: str,
    row_id: str,
    body: UpdateRowInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Callers (the admin UI) are expected to have already fetched the
    current row via GET and shown the admin an exact before-to-after
    diff before submitting -- this route re-verifies the "before" itself
    server-side rather than trusting a client-supplied snapshot, so the
    audit log's before_state is always the real value at write time."""
    result = await service.update_row(
        db, table_name, row_id, body.changes, admin.user_id
    )
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"change_id": str(result.danger_ok)}


@router.delete("/tables/{table_name}/rows/{row_id}")
async def delete_row(
    table_name: str,
    row_id: str,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await service.delete_row(db, table_name, row_id, admin.user_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"change_id": str(result.danger_ok)}


@router.get("/changes")
async def list_changes(
    limit: int = 50,
    offset: int = 0,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    limit = max(1, min(limit, 200))
    stmt = (
        select(AdminAuditLog)
        .order_by(AdminAuditLog.created_at.desc())
        .limit(limit)
        .offset(max(0, offset))
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_log_summary(log) for log in rows]


@router.post("/changes/{log_id}/revert")
async def revert_change(
    log_id: UUID,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The rollback half of the "rollback-safe design" requirement --
    replays one audit log entry's before_state back through the same
    validated write path (see domain/admin_data/service.py::revert_change),
    never a raw restore. The frontend must still show its own
    confirm+diff step (the log entry itself already contains the exact
    before/after) ahead of calling this."""
    result = await service.revert_change(db, log_id, admin.user_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"change_id": str(result.danger_ok)}
