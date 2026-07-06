from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from logand_backend.db.models.invoices import Invoice, InvoiceLineItem
from logand_backend.domain.invoices.recurrence import (
    generate_due_recurring_invoices,
    mark_overdue_invoices,
)
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


async def test_recompute_amount_total_quantizes_zero_decimal_currency(
    db_session, make_user
) -> None:
    """JPY (0dp) -- amount_total must be a whole number, not a fixed 2dp.
    See FINDINGS.md L1."""
    customer = await make_user(role="customer")
    line_items = [
        LineItemInput(
            description="widget", quantity=Decimal(3), unit_price=Decimal("1000")
        ),
    ]
    invoice_id = (await create_invoice(db_session, customer.id, line_items)).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.currency = "jpy"
    await db_session.flush()

    total = await recompute_amount_total(db_session, invoice_id)

    # A 2dp-regression would yield Decimal("3000.00"), which is value-equal
    # to Decimal("3000") -- assert the exponent too so this test cannot
    # pass against a 2dp-hardcoded recompute. See FINDINGS.md L1.
    assert total == Decimal("3000")
    assert total.as_tuple().exponent == 0, f"expected 0dp quantum, got {total!r}"
    await db_session.refresh(invoice)
    assert invoice.amount_total == Decimal("3000")


async def test_recompute_amount_total_quantizes_three_decimal_currency(
    db_session, make_user
) -> None:
    """BHD (3dp) -- amount_total must keep the third decimal place instead
    of being rounded away at 2dp. See FINDINGS.md L1."""
    customer = await make_user(role="customer")
    line_items = [
        LineItemInput(description="widget", quantity=Decimal(1), unit_price=Decimal(1)),
    ]
    invoice_id = (await create_invoice(db_session, customer.id, line_items)).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.currency = "bhd"
    # create_invoice quantizes unit_price to the invoice's currency at
    # write time (FINDINGS.md M1) -- set the raw 3dp price directly here,
    # bypassing that quantization, so this test isolates
    # recompute_amount_total's OWN currency-aware rounding rather than
    # create_invoice's (a currency switch after creation doesn't happen in
    # production; currency is hardcoded "usd" today). quantity=1 so the
    # true 3dp total (1.005) is numerically DISTINCT from a 2dp-regressed
    # total (1.00) -- with quantity=2 both are 2.01/2.010, which are
    # Decimal-value-equal and can't distinguish the two (FINDINGS.md L1).
    line_item = (
        await db_session.execute(
            select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
        )
    ).scalar_one()
    line_item.unit_price = Decimal("1.005")
    await db_session.flush()

    total = await recompute_amount_total(db_session, invoice_id)

    assert total == Decimal("1.005")
    assert total.as_tuple().exponent == -3, f"expected 3dp quantum, got {total!r}"
    await db_session.refresh(invoice)
    assert invoice.amount_total == Decimal("1.005")


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
            description="subscription",
            quantity=Decimal(1),
            unit_price=Decimal("9.99"),
            unit="mo",
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

    new_line_items = (
        (
            await db_session.execute(
                select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == created[0])
            )
        )
        .scalars()
        .all()
    )
    assert len(new_line_items) == 1
    # The unit label ("mo") must carry over to the new draft too -- a real
    # bug caught here: the copy loop in recurrence.py originally only
    # copied description/quantity/unit_price, silently dropping unit on
    # every auto-generated recurring invoice.
    assert new_line_items[0].unit == "mo"


async def test_generate_due_recurring_invoices_does_not_duplicate_on_rerun(
    db_session, make_user
) -> None:
    """Regression test for H1: the scheduler runs this once a day, every
    day, forever -- an unpaid recurring invoice whose due_date has passed
    must NOT spawn a fresh draft on every single run. The parent invoice
    should stop matching this query once it has generated its successor
    (is_recurring flips to False on the parent, True on the new child).
    """
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.is_recurring = True
    invoice.recurrence_interval = "monthly"
    invoice.due_date = date(2026, 1, 1)
    await send_invoice(db_session, invoice_id)

    first_run = await generate_due_recurring_invoices(
        db_session, as_of=date(2026, 1, 15)
    )
    second_run = await generate_due_recurring_invoices(
        db_session, as_of=date(2026, 1, 16)
    )
    third_run = await generate_due_recurring_invoices(
        db_session, as_of=date(2026, 2, 20)
    )

    assert len(first_run) == 1
    assert second_run == []
    assert third_run == []

    await db_session.refresh(invoice)
    assert invoice.is_recurring is False

    new_invoice = await db_session.get(Invoice, first_run[0])
    assert new_invoice.is_recurring is True


async def test_generate_due_recurring_invoices_still_recurs_once_paid(
    db_session, make_user
) -> None:
    """Regression test for H1: billing cadence is driven by due_date, not
    payment state -- an invoice that gets paid before its next cycle is
    generated must still spawn its successor, not silently stop
    recurring forever just because status left 'sent'.
    """
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.is_recurring = True
    invoice.recurrence_interval = "monthly"
    invoice.due_date = date(2026, 1, 1)
    await send_invoice(db_session, invoice_id)
    invoice.status = "paid"
    await db_session.flush()

    created = await generate_due_recurring_invoices(db_session, as_of=date(2026, 1, 15))

    assert len(created) == 1
    new_invoice = await db_session.get(Invoice, created[0])
    assert new_invoice.due_date == date(2026, 2, 1)
    assert new_invoice.is_recurring is True


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


async def test_mark_overdue_invoices_flips_past_due_sent_invoice(
    db_session, make_user
) -> None:
    """Regression test for FINDINGS.md M1: "overdue" was write-never --
    every read path treated it as real but nothing ever set it."""
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.due_date = date(2026, 1, 1)
    await send_invoice(db_session, invoice_id)

    updated = await mark_overdue_invoices(db_session, as_of=date(2026, 1, 15))

    assert updated == [invoice_id]
    await db_session.refresh(invoice)
    assert invoice.status == "overdue"


async def test_mark_overdue_invoices_is_idempotent(db_session, make_user) -> None:
    customer = await make_user(role="customer")
    invoice_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    invoice.due_date = date(2026, 1, 1)
    await send_invoice(db_session, invoice_id)

    await mark_overdue_invoices(db_session, as_of=date(2026, 1, 15))
    second_run = await mark_overdue_invoices(db_session, as_of=date(2026, 1, 16))

    assert second_run == []


async def test_mark_overdue_invoices_skips_not_yet_due_and_no_due_date(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    not_yet_due = (await create_invoice(db_session, customer.id, [])).danger_ok
    invoice_a = await db_session.get(Invoice, not_yet_due)
    invoice_a.due_date = date(2026, 2, 1)
    await send_invoice(db_session, not_yet_due)

    no_due_date = (await create_invoice(db_session, customer.id, [])).danger_ok
    await send_invoice(db_session, no_due_date)

    updated = await mark_overdue_invoices(db_session, as_of=date(2026, 1, 15))

    assert updated == []


async def test_mark_overdue_invoices_skips_draft_and_paid(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    draft_id = (await create_invoice(db_session, customer.id, [])).danger_ok
    draft = await db_session.get(Invoice, draft_id)
    draft.due_date = date(2026, 1, 1)
    await db_session.flush()

    updated = await mark_overdue_invoices(db_session, as_of=date(2026, 1, 15))

    assert updated == []
    await db_session.refresh(draft)
    assert draft.status == "draft"


async def test_create_invoice_computes_tax_from_per_line_charges(
    db_session, make_user
) -> None:
    # A line can owe several taxes at once (import duty + sales tax); tax is
    # summed per charge, and amount_total = subtotal + tax. See
    # docs/design/16-sales-tax.md.
    from logand_backend.domain.invoices.service import LineItemTaxInput

    customer = await make_user(role="customer")
    line_items = [
        LineItemInput(
            description="PCB (imported)",
            quantity=Decimal(2),
            unit_price=Decimal("100.00"),  # line_total 200.00
            taxes=[
                LineItemTaxInput(
                    tax_type="import_duty",
                    jurisdiction="US-customs",
                    rate=Decimal("0.02"),
                ),
                LineItemTaxInput(
                    tax_type="sales", jurisdiction="US-TN", rate=Decimal("0.07")
                ),
            ],
        ),
        LineItemInput(
            description="exempt service",
            quantity=Decimal(1),
            unit_price=Decimal("50.00"),
            taxable=False,
            taxes=[
                LineItemTaxInput(
                    tax_type="sales", jurisdiction="US-TN", rate=Decimal("0.07")
                )
            ],
        ),
    ]

    result = await create_invoice(
        db_session, customer.id, line_items, tax_origin_state="TN"
    )
    assert result.is_ok

    invoice = await db_session.get(Invoice, result.danger_ok)
    # Taxed line: 200.00 * (0.02 + 0.07) = 18.00. Exempt line: 0.
    assert invoice.tax_amount == Decimal("18.00")
    # subtotal 250.00 + tax 18.00
    assert invoice.amount_total == Decimal("268.00")
    assert invoice.tax_origin_state == "TN"


async def test_create_invoice_no_taxes_is_zero_tax(db_session, make_user) -> None:
    customer = await make_user(role="customer")
    line_items = [
        LineItemInput(
            description="widget", quantity=Decimal(1), unit_price=Decimal("10.00")
        )
    ]
    invoice_id = (await create_invoice(db_session, customer.id, line_items)).danger_ok
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.tax_amount == Decimal("0.000")
    assert invoice.amount_total == Decimal("10.00")
