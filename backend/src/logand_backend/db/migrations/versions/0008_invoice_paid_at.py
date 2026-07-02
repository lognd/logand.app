"""add paid_at to invoices

Revision ID: 0008_invoice_paid_at
Revises: 0007_documents
Create Date: 2026-07-02

See db/models/invoices.py::Invoice.paid_at's own doc comment -- set once,
at the moment status flips to "paid", across all three real transition
sites (manual payment, PayPal capture, Stripe webhook).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_invoice_paid_at"
down_revision: Union[str, None] = "0007_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoices", "paid_at")
