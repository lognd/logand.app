"""add refunds table and Stripe dispute tracking on payments

Revision ID: 0015_refunds_and_disputes
Revises: 0014_admin_audit_log
Create Date: 2026-07-02

See db/models/invoices.py::Refund's own doc comment for why refunds are
a separate table (multiple partial refunds per payment, each needing its
own audit trail) rather than a counter column on Payment, and Payment's
dispute_status/stripe_dispute_id doc comments for the Stripe dispute
lifecycle this adds (FINDINGS.md follow-up: "make the invoicing system
more expressive for refunding, and the necessary Stripe expressiveness
for disputed [charges] and whatnot").
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0015_refunds_and_disputes"
down_revision: Union[str, None] = "0014_admin_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("paypal_capture_id", sa.Text(), nullable=True))
    op.add_column("payments", sa.Column("dispute_status", sa.Text(), nullable=True))
    op.add_column("payments", sa.Column("stripe_dispute_id", sa.Text(), nullable=True))
    op.create_index(
        "uq_payments_stripe_dispute_id",
        "payments",
        ["stripe_dispute_id"],
        unique=True,
        postgresql_where="stripe_dispute_id IS NOT NULL",
    )
    op.drop_constraint("ck_payments_status", "payments", type_="check")
    op.create_check_constraint(
        "ck_payments_status",
        "payments",
        "status in ('pending','succeeded','failed','refunded','partially_refunded')",
    )
    op.create_check_constraint(
        "ck_payments_dispute_status",
        "payments",
        "dispute_status in ('needs_response','under_review','won','lost') "
        "or dispute_status is null",
    )

    op.drop_constraint("ck_invoices_status", "invoices", type_="check")
    op.create_check_constraint(
        "ck_invoices_status",
        "invoices",
        "status in ('draft','sent','paid','overdue','void','refunded')",
    )

    op.create_table(
        "refunds",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "payment_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "invoice_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("stripe_refund_id", sa.Text(), nullable=True),
        sa.Column("paypal_refund_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="succeeded"),
        sa.Column(
            "recorded_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_check_constraint(
        "ck_refunds_status", "refunds", "status in ('succeeded','failed')"
    )
    op.create_foreign_key(
        "fk_refunds_payment_id",
        "refunds",
        "payments",
        ["payment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_refunds_invoice_id",
        "refunds",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_refunds_recorded_by",
        "refunds",
        "users",
        ["recorded_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_refunds_invoice_id", "refunds", ["invoice_id"])
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
    op.create_index(
        "uq_refunds_stripe_refund_id",
        "refunds",
        ["stripe_refund_id"],
        unique=True,
        postgresql_where="stripe_refund_id IS NOT NULL",
    )
    op.create_index(
        "uq_refunds_paypal_refund_id",
        "refunds",
        ["paypal_refund_id"],
        unique=True,
        postgresql_where="paypal_refund_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_table("refunds")
    op.drop_constraint("ck_invoices_status", "invoices", type_="check")
    op.create_check_constraint(
        "ck_invoices_status",
        "invoices",
        "status in ('draft','sent','paid','overdue','void')",
    )
    op.drop_constraint("ck_payments_dispute_status", "payments", type_="check")
    op.drop_constraint("ck_payments_status", "payments", type_="check")
    op.create_check_constraint(
        "ck_payments_status",
        "payments",
        "status in ('pending','succeeded','failed','refunded')",
    )
    op.drop_index("uq_payments_stripe_dispute_id", table_name="payments")
    op.drop_column("payments", "stripe_dispute_id")
    op.drop_column("payments", "dispute_status")
    op.drop_column("payments", "paypal_capture_id")
