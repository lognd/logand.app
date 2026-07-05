"""add zip_code to payments

Revision ID: 0021_payment_zip_code
Revises: 0020_password_reset_tokens
Create Date: 2026-07-05

Retain the payer's billing postal code on each payment for sales-tax
jurisdiction and tax-audit purposes. Populated from the Stripe charge's
billing_details for card payments (see api/webhooks.py); nullable because
manual payments may have no address and existing rows predate it. See
db/models/invoices.py::Payment.zip_code.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_payment_zip_code"
down_revision: Union[str, None] = "0020_password_reset_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("zip_code", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "zip_code")
