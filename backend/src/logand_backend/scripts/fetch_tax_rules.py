"""Populate/refresh the tax_rules knowledge base (docs/design/16-sales-tax.md).

This is the "keep tax amounts up to date" job. It loads rate rules from a
SOURCE and upserts them into tax_rules with effective dating, so historical
invoices keep the rule they were issued under while new invoices price
against the current rate.

## Sources

There is no single free, complete, authoritative feed for US sales/use tax
(thousands of jurisdictions, changing constantly) or import duty (HTS
classification). Realistic options, in rough order of effort vs. correctness:

  1. A commercial tax-rate API -- TaxJar, Avalara AvaTax, Stripe Tax,
     Zip2Tax, Vertex. These are the correct answer for real compliance:
     accurate, jurisdiction-resolved, kept current. Add an adapter under
     `_PROVIDERS` that calls the API and yields RuleInput rows.
  2. Government data -- state DOR rate tables (often downloadable CSV) for
     sales/use tax; the USITC HTS / DataWeb for duty rates. Free but
     piecemeal and requires normalization per source.
  3. A curated JSON/CSV file you maintain by hand (the `file` source below).
     Fine to start -- e.g. just your home state's rate and the duty rates
     for the parts you actually import -- and the always-available fallback.

The Phase-4 design also allows an LLM-assisted ingestion step that reads a
published rate table and emits normalized RuleInput rows; keep that upstream
of this loader (it only writes what it's given) so a model error can never
perturb a rate already in the table.

## Usage

    python -m logand_backend.scripts.fetch_tax_rules --source file --path rules.json

`rules.json` is a list of objects:
    [{"jurisdiction": "US-TN", "tax_type": "sales", "category": "*",
      "rate": "0.07", "source": "TN DOR 2026"}, ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from logand_backend.app.config import AppConfig
from logand_backend.db import base as db_base
from logand_backend.db.models.tax import TaxRule
from logand_backend.logging import get_logger

_log = get_logger(__name__)


class RuleInput(BaseModel):
    """A rate rule to load. Validated before it touches the DB."""

    jurisdiction: str
    tax_type: str
    category: str = "*"
    rate: Decimal = Field(ge=0)
    source: str | None = None


def _load_file(path: Path) -> list[RuleInput]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("rules file must be a JSON list of rule objects")
    return [RuleInput.model_validate(row) for row in data]


# Pluggable sources. `file` is the always-available fallback; add commercial
# provider adapters here (each returns list[RuleInput]).
_PROVIDERS = {
    "file": _load_file,
}


async def upsert_rules(session, rules: Iterable[RuleInput]) -> tuple[int, int]:
    """Insert new rules, effective-dating out any superseded current rule for
    the same (jurisdiction, tax_type, category) whose rate actually changed.
    Returns (inserted, superseded). Idempotent: re-running with the same rates
    is a no-op (no new row, nothing closed out)."""
    now = datetime.now(timezone.utc)
    inserted = 0
    superseded = 0
    for r in rules:
        current = (
            (
                await session.execute(
                    select(TaxRule).where(
                        TaxRule.jurisdiction == r.jurisdiction,
                        TaxRule.tax_type == r.tax_type,
                        TaxRule.category == r.category,
                        TaxRule.effective_to.is_(None),
                        or_(
                            TaxRule.effective_from <= now, TaxRule.effective_from > now
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        # A single "current" (open-ended) rule is expected; if the rate is
        # unchanged, leave it alone (idempotent). Otherwise close it out.
        unchanged = any(c.rate == r.rate for c in current)
        if unchanged:
            continue
        for c in current:
            c.effective_to = now
            superseded += 1
        session.add(
            TaxRule(
                jurisdiction=r.jurisdiction,
                tax_type=r.tax_type,
                category=r.category,
                rate=r.rate,
                source=r.source,
                effective_from=now,
            )
        )
        inserted += 1
    await session.flush()
    return inserted, superseded


async def _amain() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the tax_rules knowledge base."
    )
    parser.add_argument("--source", default="file", choices=sorted(_PROVIDERS))
    parser.add_argument(
        "--path", type=Path, help="Path to the rules file (for --source file)."
    )
    args = parser.parse_args()

    # Only the `file` source exists today (argparse `choices` enforces it);
    # commercial adapters get their own branch here as they're added.
    if not args.path:
        parser.error("--source file requires --path")
    rules = _load_file(args.path)

    cfg = AppConfig.from_external(argparse.Namespace())
    db_base.init_engine(cfg.database_url)
    session = db_base.get_session()
    try:
        inserted, superseded = await upsert_rules(session, rules)
        await session.commit()
    finally:
        await session.close()
        await db_base.dispose_engine()
    _log.info(
        "tax_rules refresh complete",
        extra={"inserted": inserted, "superseded": superseded, "source": args.source},
    )
    print(f"inserted {inserted} new rule(s), superseded {superseded}")
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
