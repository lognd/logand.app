from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base

_STATUS_CHECK = "status in ('draft','sent','paid','overdue','void','refunded')"
_RECURRENCE_CHECK = (
    "recurrence_interval in ('weekly','monthly','quarterly','yearly') "
    "or recurrence_interval is null"
)
# "partially_refunded" and "refunded" are driven by Refund rows summing to
# less than / at-least the payment's own amount (see
# domain/invoices/refunds.py::refund_payment) -- never set directly by a
# caller. "disputed" is separate from all of these: a Stripe dispute can
# land on a payment regardless of whether it's also been (partially)
# refunded, tracked instead via the dispute_status/stripe_dispute_id
# columns below so the two lifecycles (refund vs. dispute) don't collide
# on one status value.
_PAYMENT_STATUS_CHECK = (
    "status in ('pending','succeeded','failed','refunded','partially_refunded')"
)
# Mirrors Stripe's own dispute.status values, collapsed to the buckets
# this app actually acts differently on: "needs_response" and
# "under_review" are both still-open (Stripe has ~6 finer-grained open
# states -- needs_response/warning_needs_response/warning_under_review/
# under_review -- collapsed to these two since this app doesn't yet do
# anything different between them), "won"/"lost" are terminal. See
# api/webhooks.py's charge.dispute.* handler for what maps to what.
_DISPUTE_STATUS_CHECK = (
    "dispute_status in ('needs_response','under_review','won','lost') "
    "or dispute_status is null"
)
_REFUND_STATUS_CHECK = "status in ('pending','succeeded','failed')"
# "stripe" stays the implicit default for the existing Stripe PaymentIntent
# flow (api/invoices_public.py's /pay + api/webhooks.py) -- the other four
# are all recorded manually by an admin (domain/invoices/service.py's
# record_manual_payment) except "paypal", which can be EITHER a real
# PayPal Orders API payment (once configured, see
# domain/payments/providers/paypal.py) OR a manually-recorded one (if an
# admin just marks a customer's already-completed PayPal transfer as
# paid instead) -- same "method" value either way, distinguished by
# whether paypal_order_id is set.
_PAYMENT_METHOD_CHECK = "method in ('stripe','paypal','zelle','in_person','other')"


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_invoices_status"),
        CheckConstraint(_RECURRENCE_CHECK, name="ck_invoices_recurrence_interval"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    # NOTE: amount_total is denormalized from invoice_line_items for query speed.
    # Must be recomputed server-side on every write -- never trust client input
    # for this field. See domain/invoices/ for the recompute helper.
    amount_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=0
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="usd")
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recurring: Mapped[bool] = mapped_column(default=False)
    recurrence_interval: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True
    )
    # Set exactly once, at the moment status flips to "paid" (see the
    # three call sites: domain/invoices/service.py's record_manual_payment,
    # api/invoices_public.py's PayPal capture route, and api/webhooks.py's
    # Stripe webhook handler) -- never touched again after that, even if
    # the invoice is later voided, so "when did this actually get paid"
    # stays answerable regardless of what happens to it afterward.
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Durable admin-facing signal for a suspected double-collect/overpayment
    # (see M2/L2 in FINDINGS.md) -- previously these were logged as a
    # warning ONLY, which nobody sees unless they're grepping logs. Set by
    # domain/invoices/service.py::flag_invoice_needs_review from the PayPal
    # capture route's overpaid branch, reconcile_pending_paypal_captures'
    # overpaid branch, and the Stripe webhook when a payment_intent
    # succeeds while a PayPal capture is still pending on the same invoice.
    # Never cleared automatically -- an admin resolves it out-of-band (e.g.
    # after issuing a manual refund); surfacing/clearing it in the admin
    # UI is future work, not part of this fix.
    needs_review: Mapped[bool] = mapped_column(default=False, nullable=False)
    needs_review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    __table_args__ = (
        # Backstop for the pydantic-layer guard in
        # domain/invoices/service.py::LineItemInput -- see FINDINGS.md
        # M-2. A negative/zero quantity or negative unit_price would
        # silently corrupt the denormalized amount_total every downstream
        # money calc trusts.
        CheckConstraint("quantity > 0", name="ck_invoice_line_items_quantity_positive"),
        CheckConstraint(
            "unit_price >= 0", name="ck_invoice_line_items_unit_price_nonnegative"
        ),
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=1)
    # Free-form ("hr", "ea", "ft"...) -- blank/null for a flat one-off
    # charge with no natural unit. Purely display: "$45.00 / hr" instead
    # of a bare "$45.00" next to unit_price, on the admin form, the
    # customer-facing view, and the PDF. Never used in amount_total math
    # (that's always quantity * unit_price regardless of what the unit
    # label says).
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(_PAYMENT_STATUS_CHECK, name="ck_payments_status"),
        CheckConstraint(_PAYMENT_METHOD_CHECK, name="ck_payments_method"),
        CheckConstraint(_DISPUTE_STATUS_CHECK, name="ck_payments_dispute_status"),
        # Backstop for the pydantic-layer guard in
        # domain/invoices/service.py::ManualPaymentInput -- see
        # FINDINGS.md M-1. A non-positive amount would corrupt
        # get_paid_so_far/get_amount_due.
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        # Defined here too, not only in migration 0003_payment_idempotency
        # -- integration/system tests build their schema from THIS
        # metadata via Base.metadata.create_all() (see conftest.py's
        # db_engine fixture), not by actually running Alembic migrations,
        # so an index that only exists in the migration file is invisible
        # to most of the test suite (confirmed: the DB-level duplicate-
        # payment test passed locally against a migrated DB but silently
        # never even created the index against create_all() until this
        # was added here too -- same gap db/models/inventory.py's own
        # NOTE describes for the FTS column). Partial (postgresql_where)
        # since most rows (manual payments) never set these at all, and
        # NULL must never be treated as colliding with NULL.
        Index(
            "uq_payments_stripe_payment_intent_id",
            "stripe_payment_intent_id",
            unique=True,
            postgresql_where=text("stripe_payment_intent_id IS NOT NULL"),
        ),
        Index(
            "uq_payments_paypal_order_id",
            "paypal_order_id",
            unique=True,
            postgresql_where=text("paypal_order_id IS NOT NULL"),
        ),
        Index(
            "uq_payments_stripe_dispute_id",
            "stripe_dispute_id",
            unique=True,
            postgresql_where=text("stripe_dispute_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    method: Mapped[str] = mapped_column(Text, nullable=False, default="stripe")
    # Nullable now (was NOT NULL) -- only ever set for method="stripe" rows;
    # a manually-recorded Zelle/in-person/other payment has no Stripe
    # object to reference at all.
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set only for method="paypal" rows created via the real PayPal Orders
    # API (domain/payments/providers/paypal.py) -- null for a manually-
    # recorded PayPal payment, same reasoning as stripe_payment_intent_id.
    paypal_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PayPal refunds are issued against a CAPTURE id, not the order id --
    # captured before capture_order's return value even reached this
    # model (see domain/payments/providers/paypal.py::PayPalCapture),
    # only set for method="paypal" rows created via the real Orders API,
    # same as paypal_order_id above.
    paypal_capture_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Both null until a real Stripe `charge.dispute.*` webhook event
    # lands on this payment's charge (api/webhooks.py) -- see
    # _DISPUTE_STATUS_CHECK above for the value set. stripe_dispute_id is
    # the idempotency key for that handler, same reasoning as
    # stripe_payment_intent_id's own uniqueness index.
    dispute_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_dispute_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which admin recorded this -- only ever set for manually-recorded
    # payments (method != "stripe" with no processor reference above);
    # null for anything created automatically from a real Stripe webhook
    # or PayPal capture, since there's no admin action to attribute there.
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Free-form reference an admin enters for a manual payment -- a Zelle
    # confirmation number, "handed cash at the Jan 5 meeting," etc. Never
    # required (a manual payment can be recorded with none), never
    # LaTeX/HTML-escaped here (that's the PDF renderer's job when this
    # ever shows up in an invoice PDF, not this model's).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Refund(Base):
    """One (partial or full) refund issued against a Payment. Deliberately
    its own table rather than a `refunded_amount` counter column on
    Payment: a single payment can be refunded in more than one
    installment (a partial refund now, another later), and each one
    needs its own amount/reason/provider-reference/timestamp for the
    audit trail -- see domain/invoices/refunds.py::refund_payment, the
    only writer of this table. A payment's total refunded amount is
    always SUM(Refund.amount) WHERE status='succeeded' for that
    payment_id, computed on read rather than cached anywhere.
    """

    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint(_REFUND_STATUS_CHECK, name="ck_refunds_status"),
        Index(
            "uq_refunds_stripe_refund_id",
            "stripe_refund_id",
            unique=True,
            postgresql_where=text("stripe_refund_id IS NOT NULL"),
        ),
        Index(
            "uq_refunds_paypal_refund_id",
            "paypal_refund_id",
            unique=True,
            postgresql_where=text("paypal_refund_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Denormalized from payment.invoice_id -- lets the admin invoice-detail
    # view fetch every refund for an invoice in one query instead of a
    # join through payments for every row.
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    # Free-form admin-entered reason ("customer cancelled," "duplicate
    # charge," ...) -- never required, never LaTeX/HTML-escaped here, same
    # convention as Payment.note.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set only for a refund actually issued through the Stripe/PayPal
    # provider API; both null for a manual-payment refund, which is pure
    # bookkeeping (the admin returned the money outside this system --
    # Zelle, cash, a manually-sent PayPal transfer -- there is no
    # provider call to make).
    stripe_refund_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    paypal_refund_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="succeeded")
    # Which admin issued this -- always set; unlike Payment.recorded_by
    # there is no automated path that creates a Refund row.
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PaymentProof(Base):
    """A customer-uploaded screenshot/receipt showing they sent a manual
    payment (Zelle, PayPal-sent-directly, etc.) -- "an optional place to
    put a screenshot or something to show that they sent something."
    Deliberately separate from Payment: a customer can upload proof
    BEFORE an admin has recorded anything (the whole point is to give
    the admin something to go on when deciding whether to record the
    payment at all), so this can't be a field on a Payment row that
    might not exist yet.
    """

    __tablename__ = "payment_proofs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
