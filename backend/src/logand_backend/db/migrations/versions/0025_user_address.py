"""add customer address fields to users

Revision ID: 0025_user_address
Revises: 0024_item_tax_classify
Create Date: 2026-07-05

Phase 6 (docs/design/16-sales-tax.md): a customer's destination address
drives the destination jurisdiction ("US-{address_state}") used by the
auto-tax categorizer (domain/invoices/tax/apply.py). All nullable -- most
existing customers predate this.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_user_address"
down_revision: Union[str, None] = "0024_item_tax_classify"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("address_line1", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("address_city", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("address_state", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("address_postal_code", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("address_country", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "address_country")
    op.drop_column("users", "address_postal_code")
    op.drop_column("users", "address_state")
    op.drop_column("users", "address_city")
    op.drop_column("users", "address_line1")
