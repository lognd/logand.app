from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Only file_path/file_hash are ever required at capture time -- every
    # other field is nullable by design (see api/receipts.py's doc
    # comment): the whole point is "snap a photo, done," with
    # vendor/amount/category filled in later, by a human or an OCR step a
    # future automated tool adds, not required up front from a phone.
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Mirrors db/models/documents.py::Document.content_type -- persisted so
    # api/receipts.py::download_file can set the same media_type on the
    # byte-streaming fallback path that api/documents.py::download_file
    # already does (see FINDINGS.md L2). Nullable because pre-migration
    # rows have no recorded value; download_file falls back to sniffing
    # only for those.
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set once this receipt has been matched to a real budget ledger entry
    # -- reconciliation is a deliberate, separate step (see
    # domain/receipts/service.py::reconcile), not automatic at capture
    # time, since a quick phone capture often happens before anyone has
    # decided the category/amount is actually correct.
    reconciled_budget_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budget_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
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
