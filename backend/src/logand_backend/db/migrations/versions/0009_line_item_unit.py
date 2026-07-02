"""add unit to invoice line items

Revision ID: 0009_line_item_unit
Revises: 0008_invoice_paid_at
Create Date: 2026-07-02

See db/models/invoices.py::InvoiceLineItem.unit's own doc comment -- a
free-form display label ("hr", "ea", "ft"), never used in amount_total
math.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_line_item_unit"
down_revision: Union[str, None] = "0008_invoice_paid_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoice_line_items",
        sa.Column("unit", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoice_line_items", "unit")
