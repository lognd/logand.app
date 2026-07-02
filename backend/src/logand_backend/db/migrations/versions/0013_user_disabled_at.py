"""add disabled_at to users

Revision ID: 0013_user_disabled_at
Revises: 0012_payment_proofs
Create Date: 2026-07-02

See db/models/users.py::User.disabled_at's own doc comment -- checked at
login (domain/auth/service.py) so a deactivated account genuinely can't
authenticate.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_user_disabled_at"
down_revision: Union[str, None] = "0012_payment_proofs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "disabled_at")
