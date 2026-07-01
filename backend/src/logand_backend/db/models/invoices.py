from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base

_STATUS_CHECK = "status in ('draft','sent','paid','overdue','void')"
_RECURRENCE_CHECK = (
    "recurrence_interval in ('weekly','monthly','quarterly','yearly') "
    "or recurrence_interval is null"
)
_PAYMENT_STATUS_CHECK = "status in ('pending','succeeded','failed','refunded')"
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
        Numeric(12, 2), nullable=False, default=0
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="usd")
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recurring: Mapped[bool] = mapped_column(default=False)
    recurrence_interval: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True
    )
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
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(_PAYMENT_STATUS_CHECK, name="ck_payments_status"),
        CheckConstraint(_PAYMENT_METHOD_CHECK, name="ck_payments_method"),
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
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
