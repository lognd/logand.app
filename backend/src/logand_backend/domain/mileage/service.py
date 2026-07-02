from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.models.mileage import MileageEntry
from logand_backend.errors import MileageError


def _resolve_distance(
    distance: Decimal | None,
    start_odometer: Decimal | None,
    end_odometer: Decimal | None,
) -> Decimal | None:
    """Minimal-input-friendly: a caller supplies EITHER a raw distance
    (the common "just tell me the trip was 12.4 miles" phone-app case) OR
    start_odometer/end_odometer (the common "photo the dashboard before
    and after" case) -- never both required. Returns None if neither form
    of input actually resolves to a usable, non-negative number.
    """
    if distance is not None:
        return distance if distance >= 0 else None
    if start_odometer is not None and end_odometer is not None:
        derived = end_odometer - start_odometer
        return derived if derived >= 0 else None
    return None


async def create_entry(
    db: AsyncSession,
    vehicle: str,
    occurred_on: date,
    *,
    distance: Decimal | None = None,
    start_odometer: Decimal | None = None,
    end_odometer: Decimal | None = None,
    purpose: str | None = None,
    business: bool = True,
    memo: str | None = None,
) -> Result[UUID, MileageError]:
    resolved = _resolve_distance(distance, start_odometer, end_odometer)
    if resolved is None:
        return Err(MileageError.InvalidDistance)

    entry_id = uuid4()
    db.add(
        MileageEntry(
            id=entry_id,
            vehicle=vehicle,
            occurred_on=occurred_on,
            start_odometer=start_odometer,
            end_odometer=end_odometer,
            distance=resolved,
            purpose=purpose,
            business=business,
            memo=memo,
        )
    )
    await db.flush()
    return Ok(entry_id)


async def delete_entry(db: AsyncSession, entry_id: UUID) -> Result[None, MileageError]:
    entry = await db.get(MileageEntry, entry_id)
    if entry is None or entry.deleted_at is not None:
        return Err(MileageError.NotFound)
    # Soft delete, not a hard DELETE -- matches the invoices/budget
    # convention elsewhere in this codebase: a mileage log is itself
    # potentially audit-relevant (tax deduction records), so "delete"
    # hides it from normal listing rather than destroying the row.
    entry.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return Ok(None)


async def list_entries(
    db: AsyncSession,
    *,
    vehicle: str | None = None,
    business: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[MileageEntry]:
    query = select(MileageEntry).where(MileageEntry.deleted_at.is_(None))
    if vehicle is not None:
        query = query.where(MileageEntry.vehicle == vehicle)
    if business is not None:
        query = query.where(MileageEntry.business == business)
    if date_from is not None:
        query = query.where(MileageEntry.occurred_on >= date_from)
    if date_to is not None:
        query = query.where(MileageEntry.occurred_on <= date_to)
    rows = (
        (await db.execute(query.order_by(MileageEntry.occurred_on.desc())))
        .scalars()
        .all()
    )
    return list(rows)
