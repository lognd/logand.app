from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


async def generate_due_recurring_invoices(db: AsyncSession, as_of: date) -> list[UUID]:
    """Walks invoices WHERE is_recurring AND status = 'sent' past their
    recurrence_interval and creates the next draft. Pure domain function so
    the scheduled-job entrypoint (docs/design/11) stays a thin wrapper that's
    easy to unit test without a real scheduler -- see docs/design/04."""
    raise NotImplementedError("query due recurring invoices; needs db.models.invoices")
