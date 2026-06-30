from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from logand_backend.db.models.invoices import Invoice
from logand_backend.domain.invoices.recurrence import generate_due_recurring_invoices
from logand_backend.domain.invoices.service import (
    LineItemInput,
    create_invoice,
    recompute_amount_total,
    send_invoice,
    void_invoice,
)
from logand_backend.errors import InvoiceError


async def test_create_invoice_computes_amount_total_from_line_items(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    line_items = [
        LineItemInput(
            description="widget", quantity=Decimal(2), unit_price=Decimal("10.00")
        ),
        LineItemInput(
            description="gizmo", quantity=Decimal(1), unit_price=Decimal("5.50")
        ),
    ]

    result = await create_invoice(db_session, customer.id, line_items, memo="test")
    assert result.is_ok

    invoice = await db_session.get(Invoice, result.danger_ok)
    assert invoice.amount_total == Decimal("25.50")
    assert invoice.status == "draft"


async def test_recompute_amount_total_ignores_stale_invoice_total(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    line_items = [
        LineItemInput(
            description="widget", quantity=Decimal(1), unit_price=Decimal("100.00")
        ),
    ]
    invoice_id = (await create_invoice(db_session, customer.id, line_items)).danger_ok

    # Simulate a tamper attempt: force the stored total to something wrong.
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.amount_total = Decimal("1.00")
    await db_session.flush()

    total = await recompute_amount_total(db_session, invoice_id)

    assert total == Decimal("100.00")
    await db_session.refresh(invoice)
    assert invoice.amount_total == Decimal("100.00")


async def test_send_invoice_draft_to_sent(db_session, make_user) -> None:
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok

    result = await send_invoice(db_session, invoice_id)

    assert result.is_ok
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.status == "sent"


async def test_send_invoice_rejects_non_draft_state(db_session, make_user) -> None:
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    await send_invoice(db_session, invoice_id)

    result = await send_invoice(db_session, invoice_id)

    assert result.is_err
    assert result.danger_err == InvoiceError.InvalidState


async def test_send_invoice_not_found(db_session) -> None:
    import uuid

    result = await send_invoice(db_session, uuid.uuid4())
    assert result.is_err
    assert result.danger_err == InvoiceError.NotFound


async def test_void_invoice_from_sent(db_session, make_user) -> None:
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    await send_invoice(db_session, invoice_id)

    result = await void_invoice(db_session, invoice_id)

    assert result.is_ok
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.status == "void"


async def test_void_invoice_rejects_draft_state(db_session, make_user) -> None:
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok

    result = await void_invoice(db_session, invoice_id)

    assert result.is_err
    assert result.danger_err == InvoiceError.InvalidState


async def test_generate_due_recurring_invoices_creates_next_draft(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    line_items = [
        LineItemInput(
            description="subscription", quantity=Decimal(1), unit_price=Decimal("9.99")
        ),
    ]
    invoice_id = (await create_invoice(db_session, customer.id, line_items)).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.is_recurring = True
    invoice.recurrence_interval = "monthly"
    invoice.due_date = date(2026, 1, 1)
    await send_invoice(db_session, invoice_id)

    created = await generate_due_recurring_invoices(db_session, as_of=date(2026, 1, 15))

    assert len(created) == 1
    new_invoice = await db_session.get(Invoice, created[0])
    assert new_invoice.status == "draft"
    assert new_invoice.due_date == date(2026, 2, 1)
    assert new_invoice.amount_total == Decimal("9.99")
    assert new_invoice.customer_id == customer.id


async def test_generate_due_recurring_invoices_skips_non_recurring(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.due_date = date(2020, 1, 1)
    await send_invoice(db_session, invoice_id)

    created = await generate_due_recurring_invoices(db_session, as_of=date.today())

    assert created == []


async def test_generate_due_recurring_invoices_skips_not_yet_due(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.is_recurring = True
    invoice.recurrence_interval = "monthly"
    invoice.due_date = date.today() + timedelta(days=30)
    await send_invoice(db_session, invoice_id)

    created = await generate_due_recurring_invoices(db_session, as_of=date.today())

    assert created == []
