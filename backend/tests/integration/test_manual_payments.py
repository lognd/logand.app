from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from logand_backend.db.models.invoices import Invoice, Payment
from logand_backend.domain.invoices.service import (
    LineItemInput,
    ManualPaymentInput,
    create_invoice,
    record_manual_payment,
    send_invoice,
)
from logand_backend.errors import InvoiceError


async def _sent_invoice(db_session, customer_id, unit_price: str = "100.00") -> str:
    result = await create_invoice(
        db_session,
        customer_id,
        [
            LineItemInput(
                description="widget",
                quantity=Decimal(1),
                unit_price=Decimal(unit_price),
            )
        ],
        memo=None,
    )
    invoice_id = result.danger_ok
    await send_invoice(db_session, invoice_id)
    return invoice_id


async def test_record_manual_payment_marks_invoice_paid_when_amount_covers_total(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id = await _sent_invoice(db_session, customer.id)

    result = await record_manual_payment(
        db_session,
        invoice_id,
        admin.id,
        ManualPaymentInput(
            method="zelle", amount=Decimal("100.00"), note="Zelle #1234"
        ),
    )
    assert result.is_ok

    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.status == "paid"
    assert invoice.paid_at is not None

    payment = await db_session.get(Payment, result.danger_ok)
    assert payment.method == "zelle"
    assert payment.status == "succeeded"
    assert payment.recorded_by == admin.id
    assert payment.note == "Zelle #1234"
    assert payment.stripe_payment_intent_id is None


async def test_record_manual_payment_leaves_invoice_payable_when_partial(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id = await _sent_invoice(db_session, customer.id, unit_price="100.00")

    result = await record_manual_payment(
        db_session,
        invoice_id,
        admin.id,
        ManualPaymentInput(method="in_person", amount=Decimal("40.00"), note="cash"),
    )
    assert result.is_ok

    invoice = await db_session.get(Invoice, invoice_id)
    # Still "sent", not "paid" -- $40 of $100 owed isn't the full amount.
    assert invoice.status == "sent"
    assert invoice.paid_at is None


async def test_record_manual_payment_sums_multiple_partial_payments_to_mark_paid(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id = await _sent_invoice(db_session, customer.id, unit_price="100.00")

    await record_manual_payment(
        db_session,
        invoice_id,
        admin.id,
        ManualPaymentInput(method="in_person", amount=Decimal("60.00")),
    )
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.status == "sent"
    assert invoice.paid_at is None

    await record_manual_payment(
        db_session,
        invoice_id,
        admin.id,
        ManualPaymentInput(method="other", amount=Decimal("40.00")),
    )
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.status == "paid"
    assert invoice.paid_at is not None

    rows = (
        (
            await db_session.execute(
                select(Payment).where(Payment.invoice_id == invoice_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2


async def test_record_manual_payment_rejects_draft_invoice(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    result = await create_invoice(
        db_session,
        customer.id,
        [
            LineItemInput(
                description="widget", quantity=Decimal(1), unit_price=Decimal("10.00")
            )
        ],
        memo=None,
    )
    invoice_id = result.danger_ok  # never sent

    payment_result = await record_manual_payment(
        db_session,
        invoice_id,
        admin.id,
        ManualPaymentInput(method="zelle", amount=Decimal("10.00")),
    )
    assert payment_result.is_err
    assert payment_result.danger_err == InvoiceError.InvalidState


async def test_record_manual_payment_rejects_nonexistent_invoice(
    db_session, make_user
) -> None:
    from uuid import uuid4

    admin = await make_user(role="admin")
    result = await record_manual_payment(
        db_session,
        uuid4(),
        admin.id,
        ManualPaymentInput(method="zelle", amount=Decimal("10.00")),
    )
    assert result.is_err
    assert result.danger_err == InvoiceError.NotFound
