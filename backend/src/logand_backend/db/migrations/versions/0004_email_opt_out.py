"""add users.emails_opted_out for CAN-SPAM unsubscribe support

Revision ID: 0004_email_opt_out
Revises: 0003_payment_idempotency
Create Date: 2026-07-01

Backfills existing rows to False (nobody has opted out yet) via the same
add-with-server_default-then-drop-it pattern used in 0002_payment_methods,
so future INSERTs go through the ORM's own default rather than a DB-side
default silently covering for a forgotten application-level value.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_email_opt_out"
down_revision: Union[str, None] = "0003_payment_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "emails_opted_out", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.alter_column("users", "emails_opted_out", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "emails_opted_out")
