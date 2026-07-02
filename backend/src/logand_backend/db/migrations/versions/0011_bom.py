"""add unit_cost to inventory_items + bill-of-materials tables

Revision ID: 0011_bom
Revises: 0010_inventory_adjustments
Create Date: 2026-07-02

See db/models/bom.py's own doc comment: material lines + labor hours/
rate + overhead percentage, per the user's own decision on BOM scope.
unit_cost on inventory_items is what makes a BOM's material-cost
computation possible at all.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0011_bom"
down_revision: Union[str, None] = "0010_inventory_adjustments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_items",
        sa.Column("unit_cost", sa.Numeric(12, 4), nullable=True),
    )

    op.create_table(
        "boms",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("labor_hours", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("labor_rate", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "overhead_percent", sa.Numeric(6, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    op.create_table(
        "bom_material_lines",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bom_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "quantity_per_unit", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("bom_id", "item_id", name="uq_bom_material_lines_bom_item"),
        sa.CheckConstraint(
            "quantity_per_unit > 0", name="ck_bom_material_lines_positive_qty"
        ),
    )
    op.create_foreign_key(
        "fk_bom_material_lines_bom_id",
        "bom_material_lines",
        "boms",
        ["bom_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_bom_material_lines_item_id",
        "bom_material_lines",
        "inventory_items",
        ["item_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_bom_material_lines_bom_id", "bom_material_lines", ["bom_id"])


def downgrade() -> None:
    op.drop_table("bom_material_lines")
    op.drop_table("boms")
    op.drop_column("inventory_items", "unit_cost")
