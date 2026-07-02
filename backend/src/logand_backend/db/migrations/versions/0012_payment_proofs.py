"""add payment_proofs table

Revision ID: 0012_payment_proofs
Revises: 0011_bom
Create Date: 2026-07-02

See db/models/invoices.py::PaymentProof's own doc comment -- a customer-
uploaded screenshot/receipt, separate from Payment since it can exist
before an admin has recorded any payment at all.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0012_payment_proofs"
down_revision: Union[str, None] = "0011_bom"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_proofs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invoice_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "uploaded_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_foreign_key(
        "fk_payment_proofs_invoice_id",
        "payment_proofs",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_payment_proofs_uploaded_by",
        "payment_proofs",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_payment_proofs_invoice_id", "payment_proofs", ["invoice_id"])


def downgrade() -> None:
    op.drop_table("payment_proofs")
