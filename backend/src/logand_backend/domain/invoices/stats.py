from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import Invoice, Payment, Refund

# Every real Invoice.status value -- fixed here rather than derived so the
# response always has one key per status (0, not missing) even when a
# status has no rows at all, which is what makes this safe for a frontend
# to index into directly without an `?? 0` on every access.
_INVOICE_STATUSES = ("draft", "sent", "paid", "overdue", "void", "refunded")
_OPEN_DISPUTE_STATUSES = ("needs_response", "under_review")


class InvoiceStatusBreakdown(BaseModel):
    model_config = {"frozen": True}

    count: int
    amount_total: Decimal


class PaymentMethodBreakdown(BaseModel):
    model_config = {"frozen": True}

    count: int
    amount: Decimal


class DisputeBreakdown(BaseModel):
    model_config = {"frozen": True}

    needs_response: int
    under_review: int
    won: int
    lost: int


class InvoiceStats(BaseModel):
    model_config = {"frozen": True}

    by_status: dict[str, InvoiceStatusBreakdown]
    # Sum of every succeeded Payment.amount, all time -- gross money that
    # has actually moved through this system, before refunds.
    total_collected: Decimal
    # Sum of every succeeded Refund.amount, all time.
    total_refunded: Decimal
    # total_collected - total_refunded -- what the business actually kept.
    net_collected: Decimal
    # Sum of amount_total for every unpaid-but-payable invoice (sent or
    # overdue) -- money owed but not yet in hand.
    outstanding: Decimal
    by_payment_method: dict[str, PaymentMethodBreakdown]
    open_disputes: int
    disputes: DisputeBreakdown


async def get_invoice_stats(db: AsyncSession) -> InvoiceStats:
    """Aggregate, read-only breakdown for the admin stats page -- every
    number here is computed fresh from invoices/payments/refunds on each
    call (no cached/denormalized counters to drift out of sync), same
    "derive, don't cache" preference as AdminPortal.tsx's own doc comment
    for why IT doesn't show summary tiles: the source of truth is this
    one endpoint, not duplicated anywhere else.
    """
    status_rows = (
        await db.execute(
            select(
                Invoice.status,
                func.count(),
                func.coalesce(func.sum(Invoice.amount_total), 0),
            )
            .where(Invoice.deleted_at.is_(None))
            .group_by(Invoice.status)
        )
    ).all()
    by_status = {
        status: InvoiceStatusBreakdown(count=0, amount_total=Decimal(0))
        for status in _INVOICE_STATUSES
    }
    for status, count, amount_total in status_rows:
        by_status[status] = InvoiceStatusBreakdown(
            count=count, amount_total=amount_total
        )

    total_collected = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status.in_(("succeeded", "refunded", "partially_refunded"))
            )
        )
    ).scalar_one()
    total_refunded = (
        await db.execute(
            select(func.coalesce(func.sum(Refund.amount), 0)).where(
                Refund.status == "succeeded"
            )
        )
    ).scalar_one()

    outstanding = (
        await db.execute(
            select(func.coalesce(func.sum(Invoice.amount_total), 0)).where(
                Invoice.deleted_at.is_(None), Invoice.status.in_(("sent", "overdue"))
            )
        )
    ).scalar_one()

    method_rows = (
        await db.execute(
            select(
                Payment.method,
                func.count(),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .where(Payment.status.in_(("succeeded", "refunded", "partially_refunded")))
            .group_by(Payment.method)
        )
    ).all()
    by_payment_method = {
        method: PaymentMethodBreakdown(count=count, amount=amount)
        for method, count, amount in method_rows
    }

    dispute_rows = (
        await db.execute(
            select(Payment.dispute_status, func.count())
            .where(Payment.dispute_status.is_not(None))
            .group_by(Payment.dispute_status)
        )
    ).all()
    dispute_counts: dict[str, int] = {
        status: count for status, count in dispute_rows if status is not None
    }
    disputes = DisputeBreakdown(
        needs_response=dispute_counts.get("needs_response", 0),
        under_review=dispute_counts.get("under_review", 0),
        won=dispute_counts.get("won", 0),
        lost=dispute_counts.get("lost", 0),
    )
    open_disputes = sum(
        dispute_counts.get(status, 0) for status in _OPEN_DISPUTE_STATUSES
    )

    return InvoiceStats(
        by_status=by_status,
        total_collected=Decimal(total_collected),
        total_refunded=Decimal(total_refunded),
        net_collected=Decimal(total_collected) - Decimal(total_refunded),
        outstanding=Decimal(outstanding),
        by_payment_method=by_payment_method,
        open_disputes=open_disputes,
        disputes=disputes,
    )
