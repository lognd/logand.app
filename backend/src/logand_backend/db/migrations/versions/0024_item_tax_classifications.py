"""add item_tax_classifications (do-as-we-go per-item cache)

Revision ID: 0024_item_tax_classify
Revises: 0023_tax_rules_and_cache
Create Date: 2026-07-05

Phase 5 (docs/design/16-sales-tax.md): the lazy per-item classification cache.
An item is classified the first time it's invoiced (by Claude or by hand),
cached by a normalized key, and reused after; a human confirms or overrides.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_item_tax_classify"
down_revision: Union[str, None] = "0023_tax_rules_and_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_tax_classifications",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("normalized_key", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default="*"),
        sa.Column("taxable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("hts_code", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("source", sa.Text(), nullable=False, server_default="claude"),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "confirmed_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'overridden')",
            name="ck_item_tax_classifications_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("item_tax_classifications")
