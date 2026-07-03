"""add needs_review / needs_review_reason to invoices

Revision ID: 0017_invoice_needs_review
Revises: 0016_receipt_content_type
Create Date: 2026-07-03

Durable admin-facing signal for a suspected double-collect/overpayment
(see M2/L2 in FINDINGS.md) -- previously these were surfaced only as a
warning log line. See db/models/invoices.py::Invoice.needs_review's own
doc comment for the call sites that set it.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_invoice_needs_review"
down_revision: Union[str, None] = "0016_receipt_content_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "invoices",
        sa.Column("needs_review_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoices", "needs_review_reason")
    op.drop_column("invoices", "needs_review")
