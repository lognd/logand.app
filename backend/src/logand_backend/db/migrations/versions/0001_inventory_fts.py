"""add inventory full-text search column and GIN index

Revision ID: 0001_inventory_fts
Revises: 0000_initial_schema
Create Date: 2026-06-30

Follows 0000_initial_schema, which now exists (`alembic revision
--autogenerate -m "initial schema"` run against a live Postgres, capturing
every table in db/models/*.py) -- `alembic upgrade head` from a genuinely
empty database previously failed outright (ALTER TABLE inventory_items ...
against a database with no inventory_items table at all, since this was
the only migration and it assumes the ORM's tables already exist).

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
down_revision: Union[str, None] = "0000_initial_schema"
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
