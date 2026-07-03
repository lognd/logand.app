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


# Statuses a recurring invoice can be in while it's still "the active cycle"
# -- billing cadence is driven by due_date, not payment state, so a PAID
# invoice must still spawn its next cycle once its due_date passes (an
# invoice that's already void/draft was never sent for this cycle at all
# and shouldn't spawn anything).
_ACTIVE_RECURRING_STATUSES = ("sent", "overdue", "paid")


async def generate_due_recurring_invoices(db: AsyncSession, as_of: date) -> list[UUID]:
    """Walks invoices WHERE is_recurring AND status in (sent/overdue/paid)
    past their recurrence_interval and creates the next draft. Pure domain
    function so the scheduled-job entrypoint (docs/design/11) stays a thin
    wrapper that's easy to unit test without a real scheduler -- see
    docs/design/04.

    Exactly one child is ever generated per due cycle: generating a child
    flips `is_recurring` off on the PARENT (it has already spawned its
    next cycle, so it must stop matching this query on every future run --
    otherwise the same due, unpaid invoice would spawn a fresh draft every
    single day the scheduler runs) and the new child carries `is_recurring
    =True` forward, becoming the next cycle's "active" row. This also
    fixes recurrence for a cycle that gets PAID before the next one is
    generated: paid invoices are included in the status filter above (billing
    cadence is about due_date, not payment state), so a paid recurring
    invoice still generates its successor instead of the chain silently
    dying.
    """
    due = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.is_recurring.is_(True),
                Invoice.status.in_(_ACTIVE_RECURRING_STATUSES),
                Invoice.due_date.is_not(None),
                Invoice.due_date <= as_of,
            )
            # skip_locked so overlapping runs (scheduled + manual catch-up,
            # per this job's docstring) each claim disjoint sets of due
            # parents instead of both reading the same row before either
            # flips is_recurring off -- without this, two concurrent runs
            # can both generate a draft child for the same billing cycle.
            .with_for_update(skip_locked=True)
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
                currency=invoice.currency,
                is_recurring=True,
                recurrence_interval=invoice.recurrence_interval,
                due_date=next_due,
            )
        )
        # The parent has now generated its successor -- stop it from
        # matching this query again (see docstring above for why this is
        # what actually prevents unbounded daily duplication).
        invoice.is_recurring = False
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
                    unit=li.unit,
                )
            )
        await db.flush()
        await recompute_amount_total(db, new_id)
        created.append(new_id)

    return created


async def mark_overdue_invoices(db: AsyncSession, as_of: date) -> list[UUID]:
    """Flips `sent` -> `overdue` for every invoice whose due_date has
    passed. `overdue` was previously write-never (see FINDINGS.md M1): it
    appeared in every read-side filter (pay routes, recurrence's own
    _ACTIVE_RECURRING_STATUSES, the frontend's PAYABLE_STATUSES) but
    nothing ever produced it, so it was permanently dead state. Only
    `sent` rows are eligible -- `overdue` ones are already flipped (this
    is idempotent day over day), and `draft`/`paid`/`void` were never
    payable in the first place. Invoices with no due_date can't be
    overdue by definition and are excluded by the WHERE below.
    """
    rows = (
        await db.execute(
            select(Invoice).where(
                Invoice.status == "sent",
                Invoice.due_date.is_not(None),
                Invoice.due_date < as_of,
                Invoice.deleted_at.is_(None),
            )
        )
    ).scalars()
    updated: list[UUID] = []
    for invoice in rows:
        invoice.status = "overdue"
        updated.append(invoice.id)
    if updated:
        await db.flush()
    return updated
