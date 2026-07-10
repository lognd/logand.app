from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base

# Phase 3/4/5 tax infrastructure (docs/design/16-sales-tax.md). Tables:
#   TaxRule -- the deterministic knowledge base: what rate applies to a
#     (jurisdiction, tax_type, category) as of a date. Populated by
#     scripts/fetch_tax_rules.py from a real rate source.
#   ItemTaxClassification -- the "do-as-we-go" per-item cache: the first time
#     an item is invoiced it is classified (by Claude or by hand); every
#     later invoice reuses it, so only genuinely-new items ever cost a model
#     call. A human confirms or overrides; a Claude classification stays
#     "pending" (auditable) until confirmed.
#   TaxCategorizationCache -- legacy input-hash cache (kept for compatibility;
#     the per-item store above is the primary cache/audit surface now).


class TaxRule(Base):
    """One rate rule: for a jurisdiction + tax type + item category, the rate
    in effect from effective_from (until effective_to, null = still current).
    Snapshotting effective dates is what makes historical invoices auditable
    against the rule that was live when they were issued.
    """

    __tablename__ = "tax_rules"
    __table_args__ = (
        CheckConstraint("rate >= 0", name="ck_tax_rules_rate_nonnegative"),
        UniqueConstraint(
            "jurisdiction",
            "tax_type",
            "category",
            "effective_from",
            name="uq_tax_rules_jurisdiction_type_category_from",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    tax_type: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="*")
    rate: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False, default=0)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Government-source citation URL for this rate (docs/design/16-sales-tax
    # .md) -- required on every admin-entered rule at the domain layer
    # (see domain/invoices/tax/citation.py); nullable here only so older
    # rows loaded before this field existed remain valid.
    citation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Classification lifecycle. A Claude result is "pending" until a human acts;
# "confirmed" accepts it as-is; "overridden" replaces it with a human choice.
# Both confirmed and overridden are human-authoritative and never re-asked.
_STATUS_CHECK = "status IN ('pending', 'confirmed', 'overridden')"


class ItemTaxClassification(Base):
    """The category/taxability decision for one KIND of item, cached by a
    normalized item key so it's decided once and reused. See
    docs/design/16-sales-tax.md Phase 5.
    """

    __tablename__ = "item_tax_classifications"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_item_tax_classifications_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Normalized item description (lowercased/whitespace-collapsed) -- the
    # cache key. Unique so an upsert refreshes in place.
    normalized_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # A representative original description, for the review UI.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="*")
    taxable: Mapped[bool] = mapped_column(nullable=False, default=True)
    # HS/HTS code for imported items (Phase: import duty). Null for domestic.
    hts_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    # "claude" or "manual" -- where this decision came from.
    source: Mapped[str] = mapped_column(Text, nullable=False, default="claude")
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The model's own justification, kept for audit; never used in the math.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TaxCategorizationCache(Base):
    """Legacy input-hash cache for the categorizer. Superseded by
    ItemTaxClassification (per-item) but kept so migration 0023 stays valid.
    """

    __tablename__ = "tax_categorization_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cache_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
