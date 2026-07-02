"""add mileage_entries table

Revision ID: 0005_mileage
Revises: 0004_email_opt_out
Create Date: 2026-07-01

New table, no backfill needed -- see db/models/mileage.py::MileageEntry
for field-by-field reasoning.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0005_mileage"
down_revision: Union[str, None] = "0004_email_opt_out"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mileage_entries",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle", sa.Text(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("start_odometer", sa.Numeric(10, 1), nullable=True),
        sa.Column("end_odometer", sa.Numeric(10, 1), nullable=True),
        sa.Column("distance", sa.Numeric(10, 1), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("business", sa.Boolean(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("distance >= 0", name="ck_mileage_entries_distance_nonneg"),
    )


def downgrade() -> None:
    op.drop_table("mileage_entries")
