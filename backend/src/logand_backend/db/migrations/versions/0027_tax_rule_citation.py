"""add citation_url to tax_rules

Revision ID: 0027_tax_rule_citation
Revises: 0026_auto_tax_flag
Create Date: 2026-07-05

Government-citation policy (docs/design/16-sales-tax.md): an admin-entered
tax_rules row must cite the government source it came from. Nullable at the
column level so older rows loaded before this field existed remain valid;
enforced as required at the domain layer (domain/invoices/tax/citation.py)
for every new admin-entered rule.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_tax_rule_citation"
down_revision: Union[str, None] = "0026_auto_tax_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tax_rules",
        sa.Column("citation_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tax_rules", "citation_url")
