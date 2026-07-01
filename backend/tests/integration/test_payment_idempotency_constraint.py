from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from logand_backend.db.models.invoices import Payment


async def _sent_invoice(db_session, customer_id) -> str:
    from logand_backend.domain.invoices.service import (
        LineItemInput,
        create_invoice,
        send_invoice,
    )

    result = await create_invoice(
        db_session,
        customer_id,
        [
            LineItemInput(
                description="widget", quantity=Decimal(1), unit_price=Decimal("10.00")
            )
        ],
        memo=None,
    )
    invoice_id = result.danger_ok
    await send_invoice(db_session, invoice_id)
    await db_session.flush()
    return invoice_id


async def test_duplicate_stripe_payment_intent_id_rejected_at_db_level(
    db_session, make_user
) -> None:
    """The application-level row locking (see
    api/invoices_public.py::pay_invoice, api/webhooks.py) is what actually
    prevents this race in practice, but this confirms the DB-level
    backstop (migration 0003_payment_idempotency) holds even if some
    future code path forgets to take the lock -- inserting two Payment
    rows with the same stripe_payment_intent_id must be physically
    impossible at the database level, not just discouraged by
    convention.
    """
    customer = await make_user(role="customer")
    invoice_id = await _sent_invoice(db_session, customer.id)

    db_session.add(
        Payment(
            invoice_id=invoice_id,
            stripe_payment_intent_id="pi_duplicate_test",
            amount=Decimal("10.00"),
            status="succeeded",
        )
    )
    await db_session.flush()

    db_session.add(
        Payment(
            invoice_id=invoice_id,
            stripe_payment_intent_id="pi_duplicate_test",
            amount=Decimal("10.00"),
            status="succeeded",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_duplicate_paypal_order_id_rejected_at_db_level(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    invoice_id = await _sent_invoice(db_session, customer.id)

    db_session.add(
        Payment(
            invoice_id=invoice_id,
            method="paypal",
            paypal_order_id="ORDER-DUPLICATE-TEST",
            amount=Decimal("10.00"),
            status="succeeded",
        )
    )
    await db_session.flush()

    db_session.add(
        Payment(
            invoice_id=invoice_id,
            method="paypal",
            paypal_order_id="ORDER-DUPLICATE-TEST",
            amount=Decimal("10.00"),
            status="succeeded",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_multiple_null_stripe_payment_intent_ids_are_fine(
    db_session, make_user
) -> None:
    """The partial unique index only applies WHERE ... IS NOT NULL --
    confirms two manually-recorded payments (which never set
    stripe_payment_intent_id at all) don't collide with each other just
    because they're both NULL."""
    customer = await make_user(role="customer")
    invoice_id = await _sent_invoice(db_session, customer.id)

    db_session.add(
        Payment(
            invoice_id=invoice_id,
            method="zelle",
            amount=Decimal("5.00"),
            status="succeeded",
        )
    )
    db_session.add(
        Payment(
            invoice_id=invoice_id,
            method="other",
            amount=Decimal("5.00"),
            status="succeeded",
        )
    )
    await db_session.flush()  # must not raise
