"""add documents table

Revision ID: 0007_documents
Revises: 0006_receipts
Create Date: 2026-07-01

New table -- see db/models/documents.py::Document for field-by-field
reasoning (generic categorized file storage for CAD/manuals/inventory
docs/other, optionally linked to a specific inventory item).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0007_documents"
down_revision: Union[str, None] = "0006_receipts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            sa.dialects.postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column(
            "inventory_item_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "category in ('cad','manual','inventory','documentation','other')",
            name="ck_documents_category",
        ),
    )
    op.alter_column("documents", "tags", server_default=None)
    op.create_foreign_key(
        "fk_documents_inventory_item_id",
        "documents",
        "inventory_items",
        ["inventory_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_table("documents")
