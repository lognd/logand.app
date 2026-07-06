"""add tax_rules knowledge base and categorizer TTL cache

Revision ID: 0023_tax_rules_and_cache
Revises: 0022_invoice_sales_tax
Create Date: 2026-07-05

Phase 3/4 infrastructure (docs/design/16-sales-tax.md): tax_rules is the
deterministic rate knowledge base (populated by scripts/fetch_tax_rules.py),
and tax_categorization_cache holds the Claude categorizer's TTL-cached output.
Both are inert until populated / a Claude key is set.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_tax_rules_and_cache"
down_revision: Union[str, None] = "0022_invoice_sales_tax"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tax_rules",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("tax_type", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default="*"),
        sa.Column("rate", sa.Numeric(8, 5), nullable=False, server_default="0"),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("rate >= 0", name="ck_tax_rules_rate_nonnegative"),
        sa.UniqueConstraint(
            "jurisdiction",
            "tax_type",
            "category",
            "effective_from",
            name="uq_tax_rules_jurisdiction_type_category_from",
        ),
    )
    op.create_index("ix_tax_rules_jurisdiction", "tax_rules", ["jurisdiction"])

    op.create_table(
        "tax_categorization_cache",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("cache_key", sa.Text(), nullable=False, unique=True),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tax_categorization_cache_expires_at",
        "tax_categorization_cache",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tax_categorization_cache_expires_at",
        table_name="tax_categorization_cache",
    )
    op.drop_table("tax_categorization_cache")
    op.drop_index("ix_tax_rules_jurisdiction", table_name="tax_rules")
    op.drop_table("tax_rules")
