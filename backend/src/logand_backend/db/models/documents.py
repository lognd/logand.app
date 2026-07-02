from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base

# Generic categorized file storage -- CAD files, inventory manuals,
# warranty/receipt-adjacent paperwork, anything that isn't specifically a
# budget-evidence file or a quick-capture receipt (those keep their own
# tables/routes since they have their own required fields and workflows).
# One flat category enum rather than a separate table per document type --
# adding a new kind of document later (e.g. "warranty") is a CHECK
# constraint edit, not a new table/migration/route set.
DOCUMENT_CATEGORIES = ("cad", "manual", "inventory", "documentation", "other")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "category in (" + ",".join(f"'{c}'" for c in DOCUMENT_CATEGORIES) + ")",
            name="ck_documents_category",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    # NOTE: must be the postgresql-dialect ARRAY, not the generic
    # sqlalchemy.ARRAY -- same reasoning as InventoryItem.tags (generic
    # ARRAY's .contains()/.any() raise NotImplementedError at query time).
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional link to a specific inventory item this document describes
    # (a CAD file for a part, a manual for a piece of equipment) -- SET
    # NULL on item delete, not CASCADE: the document (e.g. a CAD file)
    # often still has value even after the physical item it was for is
    # gone from inventory.
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="SET NULL"),
        nullable=True,
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
