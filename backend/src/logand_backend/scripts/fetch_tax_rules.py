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
  4. `hts_file` below -- a real USITC Harmonized Tariff Schedule export
     (US import duty, jurisdiction "US-customs"). Download one from
     hts.usitc.gov ("Export" on the current HTS revision) or
     dataweb.usitc.gov's tariff database export; both offer CSV/JSON/Excel
     -- save it as CSV or JSON and point --path at it. This loader does NOT
     classify items into HTS codes -- that's the Claude categorizer
     (domain/invoices/tax/categorizer.py), which proposes an hts_code per
     line; this loader only turns a published HTS rate table into
     tax_rules rows keyed by that same code (as `category`).

The Phase-4 design also allows an LLM-assisted ingestion step that reads a
published rate table and emits normalized RuleInput rows; keep that upstream
of this loader (it only writes what it's given) so a model error can never
perturb a rate already in the table.

## Usage

    python -m logand_backend.scripts.fetch_tax_rules --source file --path rules.json
    python -m logand_backend.scripts.fetch_tax_rules --source hts_file --path hts.csv

`rules.json` is a list of objects. `source` and `citation_url` are required
-- citation_url must be a government source (.gov/.mil/.us, or an
allowlisted domain like floridarevenue.com; see
domain/invoices/tax/citation.py):
    [{"jurisdiction": "US-TN", "tax_type": "sales", "category": "*",
      "rate": "0.07", "source": "TN DOR 2026",
      "citation_url": "https://www.tn.gov/revenue.html"}, ...]

`hts.csv`/`hts.json` is a USITC-style tariff export -- see `_parse_hts_file`
below for the columns it understands.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from typani.result import Err, Ok, Result

from logand_backend.app.config import AppConfig
from logand_backend.db import base as db_base
from logand_backend.db.models.tax import TaxRule
from logand_backend.domain.invoices.tax.citation import assert_government_citation
from logand_backend.logging import get_logger

_log = get_logger(__name__)


class RuleInput(BaseModel):
    """A rate rule to load. Validated before it touches the DB. Every rule
    must carry a citation_url -- the government-source policy
    (domain/invoices/tax/citation.py) is enforced separately, at the point a
    rule is about to be written, so this only checks basic URL shape."""

    jurisdiction: str
    tax_type: str
    category: str = "*"
    rate: Decimal = Field(ge=0)
    source: str = Field(min_length=1)
    citation_url: str

    @field_validator("citation_url")
    @classmethod
    def _validate_citation_url_shape(cls, v: str) -> str:
        if not v or not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("citation_url must be a non-empty http(s) URL")
        return v


def _load_file(path: Path) -> list[RuleInput]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("rules file must be a JSON list of rule objects")
    return [RuleInput.model_validate(row) for row in data]


# USITC exports use varying header spellings across CSV/JSON/Excel exports
# and across HTS revisions -- accept any of these per logical field rather
# than pinning one exact header string.
_HTS_CODE_KEYS = ("hts8", "hts_number", "hts number", "heading/subheading")
_HTS_RATE_KEYS = (
    "general_rate_of_duty",
    "general rate of duty",
    "col1_general",
    "rate",
)

# A simple ad-valorem rate: "Free", blank, or "N%" / "N.N%". Anything else
# (specific duties like "$0.02/kg", compound like "5% + $0.01/kg", or a
# conditional/column-2 rate) can't be expressed as a flat fraction of price
# and is skipped rather than silently mis-priced.
_PERCENT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")


def _parse_ad_valorem_rate(raw: str) -> Decimal | None:
    """Parses one HTS "general rate of duty" cell into a fraction (e.g.
    "2.6%" -> Decimal("0.026")). "Free" or blank -> 0. Returns None (skip,
    caller logs) for anything that isn't a plain ad-valorem percentage --
    specific ($/unit) and compound (%+$/unit) duties have no single
    price-relative rate to store here."""
    text = raw.strip()
    if not text or text.lower() == "free":
        return Decimal(0)
    match = _PERCENT_RE.match(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1)) / Decimal(100)
    except InvalidOperation:
        return None


def _hts_code_from_row(row: dict[str, str]) -> str | None:
    lower = {k.strip().lower(): v for k, v in row.items()}
    for key in _HTS_CODE_KEYS:
        value = lower.get(key)
        if value and value.strip():
            return value.strip()
    return None


def _hts_rate_from_row(row: dict[str, str]) -> str | None:
    lower = {k.strip().lower(): v for k, v in row.items()}
    for key in _HTS_RATE_KEYS:
        value = lower.get(key)
        if value is not None:
            return value
    return None


def _parse_hts_file(path: Path, year: str | None = None) -> list[RuleInput]:
    """Loads a USITC HTS tariff export (CSV or JSON, sniffed from the file
    extension) into import-duty RuleInput rows: jurisdiction="US-customs",
    tax_type="import_duty", category=<HTS code>, rate=<ad-valorem general
    duty fraction>. Rows with a specific/compound/missing rate, or with no
    recognizable HTS code column, are logged and skipped rather than
    guessed at -- see _parse_ad_valorem_rate.
    """
    if path.suffix.lower() == ".json":
        raw_rows: list[dict[str, str]] = json.loads(path.read_text())
    else:
        with path.open(newline="") as f:
            raw_rows = list(csv.DictReader(f))

    source = f"USITC HTS {year}" if year else "USITC HTS"
    rules: list[RuleInput] = []
    for row in raw_rows:
        code = _hts_code_from_row(row)
        if not code:
            _log.warning("fetch_tax_rules: hts row missing an HTS code, skipping")
            continue
        raw_rate = _hts_rate_from_row(row)
        if raw_rate is None:
            _log.warning(
                "fetch_tax_rules: hts row missing a duty-rate column, skipping",
                extra={"hts_code": code},
            )
            continue
        rate = _parse_ad_valorem_rate(raw_rate)
        if rate is None:
            _log.info(
                "fetch_tax_rules: hts row has a non-ad-valorem duty rate, "
                "skipping (specific/compound rates aren't representable "
                "as a flat fraction)",
                extra={"hts_code": code, "raw_rate": raw_rate},
            )
            continue
        rules.append(
            RuleInput(
                jurisdiction="US-customs",
                tax_type="import_duty",
                category=code,
                rate=rate,
                source=source,
                # The USITC HTS export itself is the government source for
                # every row it yields -- hts.usitc.gov is the canonical HTS
                # landing page (a .gov host).
                citation_url="https://hts.usitc.gov/",
            )
        )
    return rules


# Pluggable sources. `file` is the always-available fallback; add commercial
# provider adapters here (each returns list[RuleInput]).
_PROVIDERS = {
    "file": _load_file,
    "hts_file": _parse_hts_file,
}


async def _upsert_one_rule(
    session, r: RuleInput, now: datetime
) -> tuple[TaxRule | None, int]:
    """Effective-dates out any superseded current rule for the same
    (jurisdiction, tax_type, category) whose rate actually changed, and
    inserts a new current row. Returns (new row, superseded count); the row
    is None if the rate was unchanged (idempotent no-op -- no new row,
    nothing closed out)."""
    current = (
        (
            await session.execute(
                select(TaxRule).where(
                    TaxRule.jurisdiction == r.jurisdiction,
                    TaxRule.tax_type == r.tax_type,
                    TaxRule.category == r.category,
                    TaxRule.effective_to.is_(None),
                    or_(TaxRule.effective_from <= now, TaxRule.effective_from > now),
                )
            )
        )
        .scalars()
        .all()
    )
    # A single "current" (open-ended) rule is expected; if the rate is
    # unchanged, leave it alone (idempotent). Otherwise close it out.
    if any(c.rate == r.rate for c in current):
        return None, 0
    for c in current:
        c.effective_to = now
    row = TaxRule(
        jurisdiction=r.jurisdiction,
        tax_type=r.tax_type,
        category=r.category,
        rate=r.rate,
        source=r.source,
        citation_url=r.citation_url,
        effective_from=now,
    )
    session.add(row)
    return row, len(current)


async def upsert_rules(session, rules: Iterable[RuleInput]) -> tuple[int, int]:
    """Insert new rules, effective-dating out any superseded current rule for
    the same (jurisdiction, tax_type, category) whose rate actually changed.
    Returns (inserted, superseded). Idempotent: re-running with the same rates
    is a no-op (no new row, nothing closed out)."""
    now = datetime.now(timezone.utc)
    inserted = 0
    superseded = 0
    for r in rules:
        row, closed = await _upsert_one_rule(session, r, now)
        if row is None:
            continue
        inserted += 1
        superseded += closed
    await session.flush()
    return inserted, superseded


async def add_tax_rule(
    session, cfg: AppConfig, rule: RuleInput
) -> Result[TaxRule, str]:
    """Adds one admin-entered tax rule to the knowledge base. Rejects any
    rule whose citation_url isn't a recognized government source (see
    domain/invoices/tax/citation.py) -- Claude only ever classifies items
    into categories; a human enters and cites the rate itself. Reuses the
    same effective-dating logic as the bulk loader (upsert_rules) so a
    manually-entered rate change supersedes the prior rule the same way."""
    try:
        assert_government_citation(rule.citation_url, cfg.citation_allowed_domains)
    except ValueError as exc:
        _log.info(
            "add_tax_rule: rejected non-government citation",
            extra={"citation_url": rule.citation_url},
        )
        return Err(str(exc))
    now = datetime.now(timezone.utc)
    row, _closed = await _upsert_one_rule(session, rule, now)
    if row is None:
        # Rate unchanged from the current rule -- fetch and return it so the
        # caller still gets a row back rather than an ambiguous no-op.
        existing = (
            (
                await session.execute(
                    select(TaxRule).where(
                        TaxRule.jurisdiction == rule.jurisdiction,
                        TaxRule.tax_type == rule.tax_type,
                        TaxRule.category == rule.category,
                        TaxRule.effective_to.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            # Shouldn't happen: _upsert_one_rule only returns None when it
            # found a current rule with the same rate, so one must exist.
            _log.error(
                "add_tax_rule: unchanged rate but no current rule found",
                extra={
                    "jurisdiction": rule.jurisdiction,
                    "tax_type": rule.tax_type,
                    "category": rule.category,
                },
            )
            return Err("internal error: could not resolve the current rule")
        row = existing
    await session.flush()
    _log.info(
        "add_tax_rule: rule added",
        extra={
            "jurisdiction": rule.jurisdiction,
            "tax_type": rule.tax_type,
            "category": rule.category,
        },
    )
    return Ok(row)


async def _amain() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the tax_rules knowledge base."
    )
    parser.add_argument("--source", default="file", choices=sorted(_PROVIDERS))
    parser.add_argument("--path", type=Path, help="Path to the rules/HTS export file.")
    parser.add_argument(
        "--year",
        help="HTS revision year, recorded in the rule's source (hts_file only).",
    )
    args = parser.parse_args()

    if not args.path:
        parser.error(f"--source {args.source} requires --path")
    if args.source == "hts_file":
        rules = _parse_hts_file(args.path, args.year)
    else:
        rules = _load_file(args.path)

    cfg = AppConfig.from_external(argparse.Namespace())

    # Every rule must cite a government source before it ever touches the
    # DB -- fail the whole run rather than partially loading rates that
    # can't be traced back to an authoritative source.
    for r in rules:
        assert_government_citation(r.citation_url, cfg.citation_allowed_domains)

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
