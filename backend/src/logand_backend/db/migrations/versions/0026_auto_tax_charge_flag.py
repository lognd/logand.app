"""add auto flag to invoice_line_item_taxes

Revision ID: 0026_auto_tax_flag
Revises: 0025_user_address
Create Date: 2026-07-05

Phase 6 (docs/design/16-sales-tax.md): distinguishes a charge written by
apply_auto_tax (auto=True) from one an admin entered by hand (auto=False,
the default). apply_auto_tax only ever deletes+replaces its own auto=True
rows on a line, so a re-run of the categorizer never clobbers a
hand-entered charge.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_auto_tax_flag"
down_revision: Union[str, None] = "0025_user_address"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoice_line_item_taxes",
        sa.Column(
            "auto", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("invoice_line_item_taxes", "auto")
