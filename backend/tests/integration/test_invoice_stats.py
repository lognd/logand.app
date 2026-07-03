from __future__ import annotations

from decimal import Decimal

from logand_backend.app.config import AppConfig
from logand_backend.domain.invoices.refunds import RefundInput, refund_payment
from logand_backend.domain.invoices.service import (
    LineItemInput,
    ManualPaymentInput,
    create_invoice,
    record_manual_payment,
    send_invoice,
)
from logand_backend.domain.invoices.stats import get_invoice_stats


async def test_invoice_stats_breaks_down_status_payments_and_refunds(
    db_session, make_user
) -> None:
    import argparse

    admin = await make_user(role="admin")
    customer = await make_user(role="customer")

    # A paid invoice, refunded halfway.
    paid_id = (
        await create_invoice(
            db_session,
            customer.id,
            [
                LineItemInput(
                    description="a", quantity=Decimal(1), unit_price=Decimal("100.00")
                )
            ],
        )
    ).danger_ok
    await send_invoice(db_session, paid_id)
    payment_id = (
        await record_manual_payment(
            db_session,
            paid_id,
            admin.id,
            ManualPaymentInput(method="zelle", amount=Decimal("100.00")),
        )
    ).danger_ok
    cfg = AppConfig.from_external(argparse.Namespace())
    await refund_payment(
        db_session,
        cfg,
        paid_id,
        admin.id,
        RefundInput(payment_id=payment_id, amount=Decimal("30.00")),
    )

    # An outstanding sent invoice.
    sent_id = (
        await create_invoice(
            db_session,
            customer.id,
            [
                LineItemInput(
                    description="b", quantity=Decimal(1), unit_price=Decimal("25.00")
                )
            ],
        )
    ).danger_ok
    await send_invoice(db_session, sent_id)

    stats = await get_invoice_stats(db_session)

    assert stats.by_status["sent"].count == 1
    assert stats.by_status["sent"].amount_total == Decimal("25.00")
    assert stats.by_status["paid"].count == 1
    assert stats.by_status["paid"].amount_total == Decimal("100.00")
    # Every other status key is present with a real zero, not missing.
    assert stats.by_status["void"].count == 0

    assert stats.total_collected == Decimal("100.00")
    assert stats.total_refunded == Decimal("30.00")
    assert stats.net_collected == Decimal("70.00")
    assert stats.outstanding == Decimal("25.00")

    assert stats.by_payment_method["zelle"].count == 1
    assert stats.by_payment_method["zelle"].amount == Decimal("100.00")

    assert stats.open_disputes == 0
    assert stats.disputes.needs_response == 0


async def test_invoice_stats_excludes_payments_of_soft_deleted_invoices(
    db_session, make_user
) -> None:
    """A soft-deleted invoice's payment must not feed
    total_collected/net_collected/by_payment_method even though it drops
    out of by_status/outstanding -- otherwise the admin stats tiles stop
    reconciling with each other (see FINDINGS.md L2)."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from logand_backend.db.models.invoices import Invoice

    admin = await make_user(role="admin")
    customer = await make_user(role="customer")

    paid_id = (
        await create_invoice(
            db_session,
            customer.id,
            [
                LineItemInput(
                    description="a", quantity=Decimal(1), unit_price=Decimal("50.00")
                )
            ],
        )
    ).danger_ok
    await send_invoice(db_session, paid_id)
    await record_manual_payment(
        db_session,
        paid_id,
        admin.id,
        ManualPaymentInput(method="zelle", amount=Decimal("50.00")),
    )

    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == paid_id))
    ).scalar_one()
    invoice.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    stats = await get_invoice_stats(db_session)

    assert stats.by_status["paid"].count == 0
    assert stats.total_collected == Decimal("0")
    assert stats.net_collected == Decimal("0")
    assert stats.by_payment_method.get("zelle") is None


async def test_invoice_stats_counts_open_disputes(db_session, make_user) -> None:
    from uuid import uuid4

    from logand_backend.db.models.invoices import Payment

    customer = await make_user(role="customer")
    invoice_id = (
        await create_invoice(
            db_session,
            customer.id,
            [
                LineItemInput(
                    description="a", quantity=Decimal(1), unit_price=Decimal("42.00")
                )
            ],
        )
    ).danger_ok
    await send_invoice(db_session, invoice_id)
    db_session.add(
        Payment(
            id=uuid4(),
            invoice_id=invoice_id,
            method="stripe",
            stripe_payment_intent_id="pi_x",
            amount=Decimal("42.00"),
            status="succeeded",
            transaction_id="ch_x",
            dispute_status="needs_response",
            stripe_dispute_id="dp_x",
        )
    )
    await db_session.flush()

    stats = await get_invoice_stats(db_session)

    assert stats.open_disputes == 1
    assert stats.disputes.needs_response == 1


async def test_invoice_stats_excludes_disputes_of_soft_deleted_invoices(
    db_session, make_user
) -> None:
    """A dispute on a soft-deleted invoice must not feed open_disputes --
    the admin can no longer see or act on the invoice, so counting it
    leaves a phantom "action required" tile that never clears (see
    FINDINGS.md L1)."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from sqlalchemy import select

    from logand_backend.db.models.invoices import Invoice, Payment

    customer = await make_user(role="customer")
    invoice_id = (
        await create_invoice(
            db_session,
            customer.id,
            [
                LineItemInput(
                    description="a", quantity=Decimal(1), unit_price=Decimal("42.00")
                )
            ],
        )
    ).danger_ok
    await send_invoice(db_session, invoice_id)
    db_session.add(
        Payment(
            id=uuid4(),
            invoice_id=invoice_id,
            method="stripe",
            stripe_payment_intent_id="pi_y",
            amount=Decimal("42.00"),
            status="succeeded",
            transaction_id="ch_y",
            dispute_status="needs_response",
            stripe_dispute_id="dp_y",
        )
    )
    await db_session.flush()

    invoice = (
        await db_session.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    invoice.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    stats = await get_invoice_stats(db_session)

    assert stats.open_disputes == 0
    assert stats.disputes.needs_response == 0
