from __future__ import annotations

import argparse
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Invoice, Payment, Refund
from logand_backend.domain.invoices import refunds as refunds_module
from logand_backend.domain.invoices.refunds import RefundInput, refund_payment
from logand_backend.domain.invoices.service import (
    LineItemInput,
    ManualPaymentInput,
    create_invoice,
    record_manual_payment,
    send_invoice,
)
from logand_backend.errors import RefundError


async def _paid_invoice_with_manual_payment(
    db_session, customer_id, admin_id, unit_price: str = "100.00"
) -> tuple[str, str]:
    invoice_id = (
        await create_invoice(
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
    ).danger_ok
    await send_invoice(db_session, invoice_id)
    payment_id = (
        await record_manual_payment(
            db_session,
            invoice_id,
            admin_id,
            ManualPaymentInput(method="zelle", amount=Decimal(unit_price), note=None),
        )
    ).danger_ok
    return invoice_id, payment_id


async def test_full_refund_of_manual_payment_is_pure_bookkeeping(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id, payment_id = await _paid_invoice_with_manual_payment(
        db_session, customer.id, admin.id
    )
    cfg = AppConfig.from_external(argparse.Namespace())

    result = await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=payment_id, reason="customer cancelled"),
    )
    assert result.is_ok

    payment = await db_session.get(Payment, payment_id)
    assert payment.status == "refunded"

    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.status == "refunded"

    refund = await db_session.get(Refund, result.danger_ok)
    assert refund.amount == Decimal("100.00")
    assert refund.reason == "customer cancelled"
    assert refund.recorded_by == admin.id
    assert refund.stripe_refund_id is None
    assert refund.paypal_refund_id is None


async def test_synchronously_settled_refund_notifies_customer(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for FINDINGS.md L2: a refund the provider (or, as
    here, a manual/no-provider refund) resolves to "succeeded"
    synchronously must notify the customer from _record_refund itself --
    apply_refund_settlement (the async path) is never reached for a
    refund that never passed through "pending"."""
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id, payment_id = await _paid_invoice_with_manual_payment(
        db_session, customer.id, admin.id
    )
    cfg = AppConfig.from_external(argparse.Namespace())

    notify_mock = AsyncMock()
    monkeypatch.setattr(refunds_module, "notify_refund_settled", notify_mock)

    result = await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=payment_id, reason="customer cancelled"),
    )
    assert result.is_ok

    notify_mock.assert_awaited_once()
    call_args = notify_mock.await_args
    assert call_args.args[2].id == invoice_id  # invoice
    assert call_args.args[3] == Decimal("100.00")  # amount


async def test_partial_refund_leaves_payment_and_invoice_partially_refunded(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id, payment_id = await _paid_invoice_with_manual_payment(
        db_session, customer.id, admin.id
    )
    cfg = AppConfig.from_external(argparse.Namespace())

    result = await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=payment_id, amount=Decimal("40.00")),
    )
    assert result.is_ok

    payment = await db_session.get(Payment, payment_id)
    assert payment.status == "partially_refunded"

    invoice = await db_session.get(Invoice, invoice_id)
    # Not fully refunded yet -- an invoice with an outstanding partial
    # refund stays "paid", not "refunded" (see refund_payment's own doc
    # comment on why Invoice.status isn't overloaded for this).
    assert invoice.status == "paid"


async def test_two_partial_refunds_compose_to_a_full_refund(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id, payment_id = await _paid_invoice_with_manual_payment(
        db_session, customer.id, admin.id
    )
    cfg = AppConfig.from_external(argparse.Namespace())

    first = await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=payment_id, amount=Decimal("40.00")),
    )
    assert first.is_ok
    second = await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=payment_id, amount=Decimal("60.00")),
    )
    assert second.is_ok

    payment = await db_session.get(Payment, payment_id)
    assert payment.status == "refunded"
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.status == "refunded"


async def test_refund_exceeding_remaining_balance_is_rejected(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id, payment_id = await _paid_invoice_with_manual_payment(
        db_session, customer.id, admin.id
    )
    cfg = AppConfig.from_external(argparse.Namespace())

    await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=payment_id, amount=Decimal("60.00")),
    )
    result = await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=payment_id, amount=Decimal("60.00")),
    )

    assert result.is_err
    assert result.danger_err == RefundError.AmountExceedsBalance


async def test_refund_of_unknown_payment_is_rejected(db_session, make_user) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id, _ = await _paid_invoice_with_manual_payment(
        db_session, customer.id, admin.id
    )
    cfg = AppConfig.from_external(argparse.Namespace())

    result = await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=uuid4()),
    )

    assert result.is_err
    assert result.danger_err == RefundError.PaymentNotFound


async def test_zero_amount_refund_is_rejected(db_session, make_user) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    invoice_id, payment_id = await _paid_invoice_with_manual_payment(
        db_session, customer.id, admin.id
    )
    cfg = AppConfig.from_external(argparse.Namespace())

    result = await refund_payment(
        db_session,
        cfg,
        invoice_id,
        admin.id,
        RefundInput(payment_id=payment_id, amount=Decimal("0.00")),
    )

    assert result.is_err
    assert result.danger_err == RefundError.InvalidAmount
