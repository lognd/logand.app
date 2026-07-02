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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base

# Bill of materials -- per the user's own decision on scope: each BOM is
# a list of (inventory item, qty-per-build-unit) material lines, plus a
# labor-hours figure and an overhead percentage applied on top. This is
# what task #76 (BOM -> inventory consumption) and #77 (BOM -> invoice
# cost-breakdown import) both build on; see domain/bom/service.py for the
# actual cost-computation math.


class BillOfMaterials(Base):
    __tablename__ = "boms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Labor to build ONE unit of whatever this BOM describes -- scaled by
    # the build quantity at consumption/import time (domain/bom/service.py),
    # not stored pre-multiplied, so editing a BOM's own labor estimate
    # doesn't require touching every past build record.
    labor_hours: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0
    )
    labor_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0
    )
    # A percentage (15.00 means 15%), applied to (material + labor) --
    # see domain/bom/service.py::compute_cost_breakdown for the exact
    # formula. Not a multiplier (1.15) -- storing the human-readable
    # percentage directly is what an admin actually types into a form and
    # avoids an off-by-one-mistake class of bug (entering 15 meaning 15%
    # but it being read as a 1500% multiplier, or vice versa).
    overhead_percent: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BomMaterialLine(Base):
    __tablename__ = "bom_material_lines"
    __table_args__ = (
        # One line per (bom, item) pair -- "add 3 more resistors to this
        # BOM" means editing the existing line's quantity_per_unit, not
        # inserting a second line for the same item that some future cost
        # computation would need to remember to sum together.
        UniqueConstraint("bom_id", "item_id", name="uq_bom_material_lines_bom_item"),
        CheckConstraint(
            "quantity_per_unit > 0", name="ck_bom_material_lines_positive_qty"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    bom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boms.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # RESTRICT (not CASCADE) on item_id -- deleting an inventory item that
    # a BOM still references would silently make that BOM's material cost
    # (and stock-consumption math) wrong; the delete should fail loudly
    # instead, same reasoning as inventory_locations' own ondelete=RESTRICT.
    quantity_per_unit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
