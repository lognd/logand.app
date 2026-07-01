"""support non-Stripe payment methods (manual + PayPal)

Revision ID: 0002_payment_methods
Revises: 0001_inventory_fts
Create Date: 2026-07-01

Adds method/paypal_order_id/recorded_by/note to payments, and makes
stripe_payment_intent_id nullable there (only ever set for method="stripe"
rows now) -- see db/models/invoices.py's Payment class for the full
reasoning on each new column. Backfills every existing row's method to
"stripe" (the only method that existed before this migration), so the new
NOT NULL column with a CHECK constraint doesn't break on data already in
the table.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0002_payment_methods"
down_revision: Union[str, None] = "0001_inventory_fts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("method", sa.Text(), nullable=False, server_default="stripe"),
    )
    # server_default was only needed to backfill existing rows above --
    # drop it so future INSERTs go through the ORM's own default="stripe"
    # (db/models/invoices.py) instead of relying on a DB-side default
    # silently applying whenever the application forgets to pass one.
    op.alter_column("payments", "method", server_default=None)

    op.alter_column(
        "payments", "stripe_payment_intent_id", existing_type=sa.Text(), nullable=True
    )
    op.add_column("payments", sa.Column("paypal_order_id", sa.Text(), nullable=True))
    op.add_column(
        "payments",
        sa.Column(
            "recorded_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_payments_recorded_by_users",
        "payments",
        "users",
        ["recorded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("payments", sa.Column("note", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_payments_method",
        "payments",
        "method in ('stripe','paypal','zelle','in_person','other')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payments_method", "payments", type_="check")
    op.drop_column("payments", "note")
    op.drop_constraint("fk_payments_recorded_by_users", "payments", type_="foreignkey")
    op.drop_column("payments", "recorded_by")
    op.drop_column("payments", "paypal_order_id")
    op.alter_column(
        "payments", "stripe_payment_intent_id", existing_type=sa.Text(), nullable=False
    )
    op.drop_column("payments", "method")
