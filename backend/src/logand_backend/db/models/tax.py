from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base

# Phase 3/4 tax infrastructure (docs/design/16-sales-tax.md). Two tables:
#   TaxRule -- the deterministic knowledge base: what rate applies to a
#     (jurisdiction, tax_type, category) as of a date. Populated by
#     scripts/fetch_tax_rules.py from a real rate source. This is the
#     authoritative lookup the categorizer queries; it never invents rates.
#   TaxCategorizationCache -- the TTL cache for the Claude categorizer, so a
#     repeated invoice for the same parts doesn't re-call the model.


class TaxRule(Base):
    """One rate rule: for a jurisdiction + tax type + item category, the rate
    in effect from effective_from (until effective_to, null = still current).
    Snapshotting effective dates is what makes historical invoices auditable
    against the rule that was live when they were issued.
    """

    __tablename__ = "tax_rules"
    __table_args__ = (
        CheckConstraint("rate >= 0", name="ck_tax_rules_rate_nonnegative"),
        # At most one current rule per (jurisdiction, type, category) is
        # enforced in the loader, not here (a UNIQUE couldn't express the
        # "effective_to is null" partial condition portably); this uniqueness
        # keeps exact-duplicate rows out.
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
    # "US-TN", "US-FL", "US-customs", ... same vocabulary as the charge rows.
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # "sales", "use", "import_duty", ...
    tax_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Item category the rate keys on (e.g. "tangible-goods", "imported-
    # component", "service"). "*" is the catch-all default for a jurisdiction.
    category: Mapped[str] = mapped_column(Text, nullable=False, default="*")
    rate: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False, default=0)
    # Provenance -- which feed/authority this came from, for audit.
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class TaxCategorizationCache(Base):
    """Cached output of the Claude categorizer, keyed by a content hash of the
    inputs (item + assembly + jurisdictions). expires_at gives the TTL so a
    knowledge-base rate change eventually re-derives; a hit within TTL skips
    the model call entirely. See docs/design/16-sales-tax.md Phase 4.
    """

    __tablename__ = "tax_categorization_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # sha256 of the normalized categorizer inputs -- unique so an upsert can
    # refresh a stale entry in place.
    cache_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # The categorizer's result as JSON (list of charges per line + category).
    # Text (not JSONB) to keep this backend-agnostic and the payload opaque.
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
