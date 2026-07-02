"""add inventory_adjustments audit table

Revision ID: 0010_inventory_adjustments
Revises: 0009_line_item_unit
Create Date: 2026-07-02

See db/models/inventory.py::InventoryAdjustment's own doc comment --
append-only audit trail for every manual quantity change (and, later,
BOM-driven consumption): quantity_before/quantity_after ARE the
rollback record.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0010_inventory_adjustments"
down_revision: Union[str, None] = "0009_line_item_unit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inventory_adjustments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "item_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("quantity_before", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "adjusted_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "quantity_after = quantity_before + delta",
            name="ck_inventory_adjustments_arithmetic",
        ),
    )
    op.create_foreign_key(
        "fk_inventory_adjustments_item_id",
        "inventory_adjustments",
        "inventory_items",
        ["item_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_inventory_adjustments_adjusted_by",
        "inventory_adjustments",
        "users",
        ["adjusted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_inventory_adjustments_item_id",
        "inventory_adjustments",
        ["item_id"],
    )


def downgrade() -> None:
    op.drop_table("inventory_adjustments")
