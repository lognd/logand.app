from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.mileage import MileageEntry
from logand_backend.domain.mileage.service import (
    create_entry,
    delete_entry,
    list_entries,
)

router = APIRouter(prefix="/api/admin/mileage", tags=["admin", "mileage"])


def _entry_summary(entry: MileageEntry) -> dict:
    return {
        "id": str(entry.id),
        "vehicle": entry.vehicle,
        "occurred_on": entry.occurred_on.isoformat(),
        "start_odometer": str(entry.start_odometer) if entry.start_odometer else None,
        "end_odometer": str(entry.end_odometer) if entry.end_odometer else None,
        "distance": str(entry.distance),
        "purpose": entry.purpose,
        "business": entry.business,
        "memo": entry.memo,
    }


@router.post("")
async def create(
    vehicle: str,
    occurred_on: date,
    distance: Decimal | None = None,
    start_odometer: Decimal | None = None,
    end_odometer: Decimal | None = None,
    purpose: str | None = None,
    business: bool = True,
    memo: str | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await create_entry(
        db,
        vehicle,
        occurred_on,
        distance=distance,
        start_odometer=start_odometer,
        end_odometer=end_odometer,
        purpose=purpose,
        business=business,
        memo=memo,
    )
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


@router.get("")
async def list_mileage(
    vehicle: str | None = None,
    business: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await list_entries(
        db, vehicle=vehicle, business=business, date_from=date_from, date_to=date_to
    )
    return [_entry_summary(row) for row in rows]


@router.delete("/{entry_id}")
async def delete(
    entry_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await delete_entry(db, entry_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "deleted"}
