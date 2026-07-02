"""add admin_audit_log table

Revision ID: 0014_admin_audit_log
Revises: 0013_user_disabled_at
Create Date: 2026-07-02

See db/models/audit.py::AdminAuditLog's own doc comment -- one shared
before/after audit trail for admin user-account actions (#80) and the
generic raw-data-browser (#81). This IS the rollback record.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0014_admin_audit_log"
down_revision: Union[str, None] = "0013_user_disabled_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "admin_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_table", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("before_state", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("after_state", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_foreign_key(
        "fk_admin_audit_log_admin_id",
        "admin_audit_log",
        "users",
        ["admin_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_admin_audit_log_target", "admin_audit_log", ["target_table", "target_id"]
    )


def downgrade() -> None:
    op.drop_table("admin_audit_log")
