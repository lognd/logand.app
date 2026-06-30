"""add inventory full-text search column and GIN index

Revision ID: 0001_inventory_fts
Revises:
Create Date: 2026-06-30

NOTE(logan): there is no initial-schema migration yet -- db/models/*.py
exist but nobody has run `alembic revision --autogenerate -m "initial
schema"` against a live Postgres to capture them. This migration is
written standalone (down_revision=None) so it isn't lost, but it is NOT
safe to run until an initial-schema migration exists ahead of it. Once
that's generated, rename this file's down_revision to point at it and
bump this file's own revision id so it's no longer "first".

The tsvector column here can't be expressed as a plain SQLAlchemy
mapped_column (see db/models/inventory.py's NOTE and
docs/design/06-inventory.md "Search"), hence hand-authoring it rather
than relying on autogenerate.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op

revision: str = "0001_inventory_fts"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_items",
        sa.Column(
            "search_vector",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', name || ' ' || coalesce(description, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_inventory_items_search_vector",
        "inventory_items",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_items_search_vector", table_name="inventory_items")
    op.drop_column("inventory_items", "search_vector")
