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
    # Sum of every succeeded/refunded/partially_refunded Payment.amount,
    # all time -- gross money that has actually moved through this
    # system, before refunds and disputes. Matches by_payment_method.
    total_collected: Decimal
    # Sum of every succeeded Refund.amount, all time.
    total_refunded: Decimal
    # total_collected - total_refunded - the still-outstanding (i.e. not
    # already reflected in total_refunded) portion of lost-dispute
    # clawbacks -- what the business actually kept.
    net_collected: Decimal
    # Sum, over every unpaid-but-payable invoice (sent or overdue), of
    # amount_total minus that invoice's own net payments so far (floored
    # at zero per invoice) -- money still owed but not yet in hand. NOT
    # raw amount_total: a partially-paid-but-still-open invoice (e.g. a
    # manual partial payment that doesn't cover the full total) already
    # has its paid portion counted in total_collected, so counting the
    # invoice's full amount_total here too would double-count that money
    # -- see FINDINGS.md L1.
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

    # Every money query below joins through Invoice and applies the SAME
    # deleted_at.is_(None) predicate as by_status/outstanding above -- a
    # soft-deleted invoice's payments/refunds must not feed these totals,
    # or a paid invoice that gets soft-deleted leaves by_status/outstanding
    # but keeps inflating total_collected/net_collected/by_payment_method,
    # and the admin stats tiles stop reconciling with each other (see
    # FINDINGS.md L2).
    total_collected = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .select_from(Payment)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(
                Payment.status.in_(("succeeded", "refunded", "partially_refunded")),
                Invoice.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    total_refunded = (
        await db.execute(
            select(func.coalesce(func.sum(Refund.amount), 0))
            .select_from(Refund)
            .join(Payment, Payment.id == Refund.payment_id)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(Refund.status == "succeeded", Invoice.deleted_at.is_(None))
        )
    ).scalar_one()
    # A dispute Stripe resolved "lost" means the funds were clawed back --
    # the Payment row stays "succeeded" (that's still an accurate record
    # of what happened at charge time; see api/webhooks.py's
    # _handle_dispute_event doc comment for why dispute status is tracked
    # separately from payment status), but counting it in net_collected
    # would overstate revenue by money Stripe already took back.
    #
    # Only count payments that are actually in the "collected" population
    # (succeeded/refunded/partially_refunded) -- a lost dispute on a
    # payment in some other status never contributed to total_collected
    # in the first place. And only count the portion of each payment's
    # amount that ISN'T already covered by a succeeded Refund, since that
    # portion is already subtracted once via total_refunded -- otherwise
    # a payment that is both refunded and dispute-"lost" would be
    # subtracted twice.
    refunded_by_payment = (
        select(
            Refund.payment_id.label("payment_id"),
            func.sum(Refund.amount).label("refunded"),
        )
        .where(Refund.status == "succeeded")
        .group_by(Refund.payment_id)
        .subquery()
    )
    lost_dispute_amount = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        Payment.amount
                        - func.coalesce(refunded_by_payment.c.refunded, 0)
                    ),
                    0,
                )
            )
            .select_from(Payment)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .outerjoin(
                refunded_by_payment,
                refunded_by_payment.c.payment_id == Payment.id,
            )
            .where(
                Payment.dispute_status == "lost",
                Payment.status.in_(("succeeded", "refunded", "partially_refunded")),
                Invoice.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    # Net-of-refunds paid-so-far per invoice -- same subquery shape as
    # domain/invoices/service.py::get_paid_so_far (a partially_refunded
    # payment still contributes its unrefunded remainder), just computed
    # in bulk across every open invoice rather than one at a time, since
    # this is an aggregate stats query rather than a single-invoice call.
    # Reuses refunded_by_payment (defined above for lost_dispute_amount)
    # rather than redefining the same subquery a second time.
    paid_by_invoice = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.sum(
                Payment.amount - func.coalesce(refunded_by_payment.c.refunded, 0)
            ).label("paid"),
        )
        .select_from(Payment)
        .outerjoin(refunded_by_payment, refunded_by_payment.c.payment_id == Payment.id)
        .where(Payment.status.in_(("succeeded", "partially_refunded")))
        .group_by(Payment.invoice_id)
        .subquery()
    )
    outstanding_rows = (
        await db.execute(
            select(Invoice.amount_total, func.coalesce(paid_by_invoice.c.paid, 0))
            .outerjoin(paid_by_invoice, paid_by_invoice.c.invoice_id == Invoice.id)
            .where(
                Invoice.deleted_at.is_(None), Invoice.status.in_(("sent", "overdue"))
            )
        )
    ).all()
    outstanding = sum(
        (
            max(Decimal(amount_total) - Decimal(paid), Decimal(0))
            for amount_total, paid in outstanding_rows
        ),
        Decimal(0),
    )

    method_rows = (
        await db.execute(
            select(
                Payment.method,
                func.count(),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .select_from(Payment)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(
                Payment.status.in_(("succeeded", "refunded", "partially_refunded")),
                Invoice.deleted_at.is_(None),
            )
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
            .select_from(Payment)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(
                Payment.dispute_status.is_not(None),
                Invoice.deleted_at.is_(None),
            )
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

    gross_total_collected = Decimal(total_collected)
    net_collected = (
        gross_total_collected - Decimal(total_refunded) - Decimal(lost_dispute_amount)
    )
    return InvoiceStats(
        by_status=by_status,
        total_collected=gross_total_collected,
        total_refunded=Decimal(total_refunded),
        net_collected=net_collected,
        outstanding=Decimal(outstanding),
        by_payment_method=by_payment_method,
        open_disputes=open_disputes,
        disputes=disputes,
    )
