"""add tax model: line classification, per-line tax charges, invoice rollups

Revision ID: 0022_invoice_sales_tax
Revises: 0021_payment_zip_code
Create Date: 2026-07-05

Phase 1 of the tax model (docs/design/16-sales-tax.md): line-item
taxable/tax_category classification, a normalized invoice_line_item_taxes
child table (one row per tax charge -- a line can owe import duty AND
sales/use tax), an invoice tax_amount rollup, and the tax_origin_state
jurisdiction snapshot. All additive/defaulted so existing invoices read back
as zero-tax (amount_total unchanged).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_invoice_sales_tax"
down_revision: Union[str, None] = "0021_payment_zip_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column(
            "tax_amount",
            sa.Numeric(14, 3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "invoices",
        sa.Column("tax_origin_state", sa.Text(), nullable=True),
    )
    op.add_column(
        "invoice_line_items",
        sa.Column(
            "taxable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "invoice_line_items",
        sa.Column("tax_category", sa.Text(), nullable=True),
    )
    op.create_table(
        "invoice_line_item_taxes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "line_item_id",
            sa.UUID(),
            sa.ForeignKey("invoice_line_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tax_type", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=True),
        sa.Column("rate", sa.Numeric(8, 5), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rate >= 0", name="ck_invoice_line_item_taxes_rate_nonnegative"
        ),
    )
    op.create_index(
        "ix_invoice_line_item_taxes_line_item_id",
        "invoice_line_item_taxes",
        ["line_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invoice_line_item_taxes_line_item_id",
        table_name="invoice_line_item_taxes",
    )
    op.drop_table("invoice_line_item_taxes")
    op.drop_column("invoice_line_items", "tax_category")
    op.drop_column("invoice_line_items", "taxable")
    op.drop_column("invoices", "tax_origin_state")
    op.drop_column("invoices", "tax_amount")
