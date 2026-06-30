from __future__ import annotations

import calendar
from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import Invoice, InvoiceLineItem
from logand_backend.domain.invoices.service import recompute_amount_total

_MONTH_STEPS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def _advance(d: date, interval: str | None) -> date:
    """Adds one period of `interval` to `d`. Deliberately avoids pulling in
    python-dateutil for one function -- month/year math here is the only
    non-trivial bit, everything else is plain timedelta."""
    if interval == "weekly":
        return d + timedelta(weeks=1)
    if interval in _MONTH_STEPS:
        months_total = d.month - 1 + _MONTH_STEPS[interval]
        year = d.year + months_total // 12
        month = months_total % 12 + 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    # NOTE: the DB CheckConstraint on recurrence_interval already restricts
    # this to one of the four known values or null; an unrecognized value
    # here means a recurring invoice with no interval, which is a data bug,
    # not something to silently skip billing for -- fail loud.
    raise ValueError(f"unrecognized recurrence_interval: {interval!r}")


async def generate_due_recurring_invoices(db: AsyncSession, as_of: date) -> list[UUID]:
    """Walks invoices WHERE is_recurring AND status = 'sent' past their
    recurrence_interval and creates the next draft. Pure domain function so
    the scheduled-job entrypoint (docs/design/11) stays a thin wrapper that's
    easy to unit test without a real scheduler -- see docs/design/04."""
    due = (
        await db.execute(
            select(Invoice).where(
                Invoice.is_recurring.is_(True),
                Invoice.status == "sent",
                Invoice.due_date.is_not(None),
                Invoice.due_date <= as_of,
            )
        )
    ).scalars()

    created: list[UUID] = []
    for invoice in due:
        new_id = uuid4()
        # The query above filters due_date.is_not(None); narrow the static
        # type to match what's already guaranteed at runtime.
        assert invoice.due_date is not None
        next_due = _advance(invoice.due_date, invoice.recurrence_interval)

        db.add(
            Invoice(
                id=new_id,
                customer_id=invoice.customer_id,
                status="draft",
                memo=invoice.memo,
                is_recurring=True,
                recurrence_interval=invoice.recurrence_interval,
                due_date=next_due,
            )
        )
        await db.flush()

        line_items = (
            await db.execute(
                select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id)
            )
        ).scalars()
        for li in line_items:
            db.add(
                InvoiceLineItem(
                    id=uuid4(),
                    invoice_id=new_id,
                    description=li.description,
                    quantity=li.quantity,
                    unit_price=li.unit_price,
                )
            )
        await db.flush()
        await recompute_amount_total(db, new_id)
        created.append(new_id)

    return created
