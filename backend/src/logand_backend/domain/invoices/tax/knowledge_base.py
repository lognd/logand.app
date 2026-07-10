from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.tax import TaxRule

# The deterministic half of the tax engine (docs/design/16-sales-tax.md,
# Phase 4 component 1). Given a jurisdiction + tax type + item category, it
# returns the rate that was in effect at a point in time -- a pure lookup
# over tax_rules, never an LLM. The categorizer decides WHICH (jurisdiction,
# type, category) tuples apply to a line; this decides the rate.


async def lookup_rate(
    db: AsyncSession,
    *,
    jurisdiction: str,
    tax_type: str,
    category: str,
    at: datetime | None = None,
) -> tuple[Decimal, TaxRule] | None:
    """The rate for (jurisdiction, tax_type, category) effective at `at`
    (default: now), plus the rule it came from for provenance. A category with
    no specific rule falls back to the jurisdiction's "*" catch-all. Returns
    None when nothing applies (the caller then attaches no charge for it,
    rather than guessing a rate).
    """
    when = at or datetime.now(timezone.utc)
    # Prefer an exact category match over the "*" catch-all: order so the
    # specific rule (category == the asked category) sorts before "*", and
    # newer effective_from before older, then take the first.
    stmt = (
        select(TaxRule)
        .where(
            TaxRule.jurisdiction == jurisdiction,
            TaxRule.tax_type == tax_type,
            TaxRule.category.in_([category, "*"]),
            TaxRule.effective_from <= when,
            or_(TaxRule.effective_to.is_(None), TaxRule.effective_to > when),
        )
        .order_by(
            # exact-category rules first (category != "*"), then most recent.
            (TaxRule.category == "*"),
            TaxRule.effective_from.desc(),
        )
    )
    rule = (await db.execute(stmt)).scalars().first()
    if rule is None:
        return None
    return rule.rate, rule
