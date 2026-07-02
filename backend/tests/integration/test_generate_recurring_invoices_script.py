from __future__ import annotations

from datetime import date
from decimal import Decimal

from logand_backend.db.models.invoices import Invoice
from logand_backend.domain.invoices.service import (
    LineItemInput,
    create_invoice,
    send_invoice,
)
from logand_backend.scripts.generate_recurring_invoices import run

# Exercises the standalone scheduler entrypoint's own wrapper logic (call
# the domain function through an injected session, commit, collect ids)
# -- not a re-test of generate_due_recurring_invoices itself, which
# tests/integration/test_invoices_service.py already covers directly.
# Passing `session=db_session` reuses the same testcontainer-backed
# engine tests/conftest.py already initialized, so this never touches
# AppConfig/a second real database connection.


async def test_run_with_injected_session_generates_and_commits(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    invoice_id = (
        await create_invoice(
            db_session,
            customer.id,
            [
                LineItemInput(
                    description="hosting",
                    quantity=Decimal(1),
                    unit_price=Decimal("9.99"),
                )
            ],
        )
    ).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.is_recurring = True
    invoice.recurrence_interval = "monthly"
    invoice.due_date = date(2026, 1, 1)
    await send_invoice(db_session, invoice_id)

    created = await run(session=db_session, as_of=date(2026, 1, 15))

    assert len(created) == 1
    new_invoice = await db_session.get(Invoice, created[0])
    assert new_invoice is not None
    assert new_invoice.status == "draft"


async def test_run_with_nothing_due_returns_empty_list(db_session, make_user) -> None:
    created = await run(session=db_session, as_of=date(2026, 1, 15))
    assert created == []
