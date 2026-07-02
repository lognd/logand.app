from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base


class InventoryLocation(Base):
    __tablename__ = "inventory_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_locations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # NOTE: must be the postgresql-dialect ARRAY, not the generic
    # sqlalchemy.ARRAY -- the generic one's .contains()/.any() raise
    # NotImplementedError at query time (caught by a real integration test,
    # see tests/integration/test_inventory_service.py).
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    # Nullable -- most existing items were created before this field
    # existed, and plenty of tracked inventory (donated parts, scrap
    # stock) genuinely has no per-unit cost worth recording. Only
    # required in practice for an item a BOM (domain/bom/) references as
    # a material line -- computing that BOM's material cost with a null
    # unit_cost is a real, surfaced error (BomError.MissingUnitCost), not
    # a silent zero.
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # NOTE: free-text search uses a Postgres GIN-indexed tsvector, added via
    # an Alembic migration (not expressible cleanly as a mapped_column) --
    # see docs/design/06-inventory.md "Search" section.


class InventoryAdjustment(Base):
    """A real, permanent audit trail row for every manual quantity change
    -- the "save a backup to rollback bad changes... see exactly what
    changed from what to what" requirement, applied to inventory.
    Deliberately append-only (no update/delete route ever touches this
    table): quantity_before/quantity_after together ARE the rollback
    record (to undo a bad adjustment, apply a new one with the reverse
    delta -- see domain/inventory/service.py's reverse_adjustment), and
    reason/adjusted_by/created_at answer "who changed this, when, and
    why" for good. BOM-driven consumption (task #76) writes through this
    exact same table with its own reason text, so there is one single
    place that ever explains why an item's quantity moved.
    """

    __tablename__ = "inventory_adjustments"
    __table_args__ = (
        CheckConstraint(
            "quantity_after = quantity_before + delta",
            name="ck_inventory_adjustments_arithmetic",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_before: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable -- a BOM-driven consumption (task #76) has no single admin
    # to attribute (it's triggered by a "record this build" action, not a
    # manual quantity edit), same nullable-for-non-manual-actions
    # convention as db/models/invoices.py::Payment.recorded_by.
    adjusted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
