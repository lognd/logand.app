"""add contact users and email verification

Revision ID: 0022_contact_users_verification
Revises: 0021_payment_zip_code
Create Date: 2026-07-09

docs/design/16-contact-users-and-email-verification.md: widens what a
`users` row is allowed to mean (contact / unverified / active, see the
design doc's state table) so an invoice can be addressed to an email
with no account yet, without forking invoices.customer_id into a
nullable "user or email" join.

password_hash goes NOT NULL -> NULL (NULL = contact, no account, nothing
can authenticate as it). email_verified_at is new -- gates login AND
every customer-facing invoice read path (the doc's "load-bearing
invariant").

THE BACKFILL BELOW IS CRITICAL: every existing row predates this
feature and has a real password, so every one of them gets
email_verified_at = now() here. Skipping it would lock the entire
existing customer base -- and the seeded admin -- out of login the
moment this migration runs.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0022_contact_users_verification"
down_revision: Union[str, None] = "0021_payment_zip_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # CRITICAL: backfill every existing row as verified -- see this
    # migration's module docstring. Every row that reaches this UPDATE
    # already has a NOT NULL password_hash (the column was NOT NULL until
    # the alter_column just above), so this is exactly the "active" state
    # from docs/design/16's table.
    op.execute("UPDATE users SET email_verified_at = now()")

    op.create_check_constraint(
        "ck_users_contact_or_active",
        "users",
        "email_verified_at is null or password_hash is not null",
    )

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "purpose in ('verify', 'claim')",
            name="ck_email_verification_tokens_purpose",
        ),
    )


def downgrade() -> None:
    op.drop_table("email_verification_tokens")
    op.drop_constraint("ck_users_contact_or_active", "users", type_="check")
    op.drop_column("users", "email_verified_at")
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
