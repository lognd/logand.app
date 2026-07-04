"""add password_reset_tokens table

Revision ID: 0020_password_reset_tok
Revises: 0019_invoice_money_precision
Create Date: 2026-07-04

Backs the self-serve "forgot password" flow (domain/auth/password_reset.py).
Single-use, short-lived tokens -- token_hash mirrors sessions.token_hash's
own discipline (sha256 of a secrets.token_urlsafe(32) value, never the raw
token itself), used_at distinguishes "not yet redeemed" from "already
redeemed" so a captured token can't be replayed even within its TTL.
Revision id kept <= 32 chars: alembic_version.version_num is VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_password_reset_tok"
down_revision: Union[str, None] = "0019_invoice_money_precision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )


def downgrade() -> None:
    op.drop_table("password_reset_tokens")
