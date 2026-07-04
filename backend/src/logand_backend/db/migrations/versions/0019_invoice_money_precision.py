"""widen invoice-money Numeric columns to 3 decimal places

Revision ID: 0019_invoice_money_precision
Revises: 0018_payment_amount_checks
Create Date: 2026-07-04

FINDINGS.md L1: the app models zero-decimal (JPY, KRW, ...) and
three-decimal (BHD, KWD, ...) currencies (domain/payments/currency.py),
but every invoice-money column was fixed at Numeric(_, 2) -- fine for
storage of a JPY amount (still an exact integer at 2dp) but too narrow to
ever store a real fractional BHD/KWD amount at its native 3dp precision.
Widens invoices.amount_total, invoice_line_items.quantity/unit_price, and
payments.amount/refunds.amount from Numeric(_, 2) to Numeric(_, 3)
(precision bumped by 2 alongside the scale bump by 1, matching the
model's new Numeric(14, 3)/(12, 3) declarations in db/models/invoices.py)
so a 3dp currency's amounts round-trip exactly instead of being silently
truncated to 2dp by the column type itself. Existing 2dp values are
untouched by a widen (ALTER COLUMN TYPE onto a wider NUMERIC is lossless).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import Numeric

revision: str = "0019_invoice_money_precision"
down_revision: Union[str, None] = "0018_payment_amount_checks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS: list[tuple[str, str, int, int]] = [
    ("invoices", "amount_total", 14, 3),
    ("invoice_line_items", "quantity", 12, 3),
    ("invoice_line_items", "unit_price", 14, 3),
    ("payments", "amount", 14, 3),
    ("refunds", "amount", 14, 3),
]

# Old (precision, scale) for every column above, in the same order --
# used by downgrade() to narrow back exactly. A downgrade after any real
# 3dp value has been written is lossy (silently rounds to 2dp), same as
# any other narrowing migration; that's an accepted, documented tradeoff
# of running downgrade at all, not something this migration can prevent.
_OLD_PRECISION_SCALE: list[tuple[int, int]] = [
    (12, 2),
    (10, 2),
    (12, 2),
    (12, 2),
    (12, 2),
]


def upgrade() -> None:
    for table, column, precision, scale in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=Numeric(precision, scale),
            postgresql_using=f"{column}::numeric({precision},{scale})",
        )


def downgrade() -> None:
    for (table, column, _precision, _scale), (old_precision, old_scale) in zip(
        _COLUMNS, _OLD_PRECISION_SCALE
    ):
        op.alter_column(
            table,
            column,
            type_=Numeric(old_precision, old_scale),
            postgresql_using=f"{column}::numeric({old_precision},{old_scale})",
        )
