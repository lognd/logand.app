"""add content_type to receipts

Revision ID: 0016_receipt_content_type
Revises: 0015_refunds_and_disputes
Create Date: 2026-07-03

See db/models/receipts.py::Receipt.content_type's own doc comment --
consumed by api/receipts.py::download_file so the byte-streaming fallback
path can set a real Content-Type instead of forcing the browser to sniff
(FINDINGS.md L2). Nullable: pre-migration rows have no recorded value.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_receipt_content_type"
down_revision: Union[str, None] = "0015_refunds_and_disputes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("content_type", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("receipts", "content_type")
