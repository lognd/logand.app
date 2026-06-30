from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base

_STATUS_CHECK = "status in ('draft','sent','paid','overdue','void')"
_RECURRENCE_CHECK = "recurrence_interval in ('weekly','monthly','quarterly','yearly') or recurrence_interval is null"
_PAYMENT_STATUS_CHECK = "status in ('pending','succeeded','failed','refunded')"


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_invoices_status"),
        CheckConstraint(_RECURRENCE_CHECK, name="ck_invoices_recurrence_interval"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    # NOTE: amount_total is denormalized from invoice_line_items for query speed.
    # Must be recomputed server-side on every write -- never trust client input
    # for this field. See domain/invoices/ for the recompute helper.
    amount_total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="usd")
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recurring: Mapped[bool] = mapped_column(default=False)
    recurrence_interval: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint(_PAYMENT_STATUS_CHECK, name="ck_payments_status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    stripe_payment_intent_id: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    transaction_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
