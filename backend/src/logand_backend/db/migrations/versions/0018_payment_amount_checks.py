"""add positivity check constraints to payments/invoice_line_items

Revision ID: 0018_payment_amount_checks
Revises: 0017_invoice_needs_review
Create Date: 2026-07-04

DB-level backstop for the pydantic-layer guards added for FINDINGS.md
M-1 (ManualPaymentInput.amount) and M-2 (LineItemInput.quantity /
unit_price) -- mirrors the refund_payment guard (RefundError.InvalidAmount
on amount <= 0) so the invariant holds even for rows written outside the
API boundary. Revision id kept <= 32 chars: alembic_version.version_num
is VARCHAR(32) (see test_migrations.py's from-empty-database test).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0018_payment_amount_checks"
down_revision: Union[str, None] = "0017_invoice_needs_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_payments_amount_positive",
        "payments",
        "amount > 0",
    )
    op.create_check_constraint(
        "ck_invoice_line_items_quantity_positive",
        "invoice_line_items",
        "quantity > 0",
    )
    op.create_check_constraint(
        "ck_invoice_line_items_unit_price_nonnegative",
        "invoice_line_items",
        "unit_price >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_invoice_line_items_unit_price_nonnegative",
        "invoice_line_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_invoice_line_items_quantity_positive",
        "invoice_line_items",
        type_="check",
    )
    op.drop_constraint("ck_payments_amount_positive", "payments", type_="check")
