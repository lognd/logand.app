from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.models.tax import TaxCategorizationCache, TaxRule
from logand_backend.logging import get_logger

# Phase 4 component 2 (docs/design/16-sales-tax.md): the Claude categorizer.
#
# Division of authority (this is the whole audit story):
#   - Claude ONLY classifies each line into a tax_category that already
#     exists in the knowledge base, and decides taxable yes/no. It never
#     invents a rate, a jurisdiction, or a tax type.
#   - Every field it returns is enforced with pydantic AND re-checked against
#     the DB's own category vocabulary; an out-of-vocabulary category is
#     coerced to the "*" catch-all rather than trusted.
#   - Rates come from knowledge_base.lookup_rate (deterministic).
#   - The validated decision (with the model's own rationale, the model id,
#     and a timestamp) is PERSISTED in tax_categorization_cache, which is both
#     the TTL cache and the audit record -- you can always answer "why did
#     this line get taxed this way, and what decided it."
#
# Inert until ANTHROPIC_API_KEY is set: is_configured() gates every call.

_log = get_logger(__name__)


def is_configured(cfg: AppConfig) -> bool:
    """True once a Claude key is set. Every entry point checks this first, so
    an unconfigured deployment silently falls back to admin-entered charges
    instead of erroring."""
    return bool(cfg.anthropic_api_key)


@dataclass(frozen=True)
class LineInput:
    """One line to classify. `context` carries anything extra that helps
    classification -- most importantly a BoM breakdown of the assembly, so
    the model can reason about the finished product AND its components."""

    index: int
    description: str
    context: str | None = None


class LineTaxDecision(BaseModel):
    """Claude's per-line decision, enforced. `category` is validated against
    the DB vocabulary by the caller (not trusted from the model)."""

    model_config = {"frozen": True}

    line_index: int
    category: str
    taxable: bool
    # The model's own justification -- persisted for audit, never used in the
    # money math.
    rationale: str = Field(default="")


class CategorizerResult(BaseModel):
    model_config = {"frozen": True}

    decisions: list[LineTaxDecision]


@dataclass(frozen=True)
class TaxCharge:
    tax_type: str
    jurisdiction: str
    rate: Decimal


@dataclass(frozen=True)
class LinePricing:
    """What the caller turns into InvoiceLineItemTax rows: the audited
    category/taxable decision plus the deterministically-priced charges."""

    line_index: int
    category: str
    taxable: bool
    rationale: str
    charges: list[TaxCharge]


async def _known_categories(db: AsyncSession) -> list[str]:
    """The category vocabulary Claude is allowed to choose from -- distinct
    categories present in tax_rules, plus the "*" catch-all. Pulling this from
    the DB (rather than hardcoding) is what keeps the model's choices inside
    the schema the knowledge base actually prices."""
    rows = (await db.execute(select(TaxRule.category).distinct())).scalars().all()
    cats = {c for c in rows if c and c != "*"}
    cats.add("*")
    return sorted(cats)


async def _kb_context(db: AsyncSession, jurisdictions: list[str]) -> str:
    """A compact, deterministic snapshot of the relevant knowledge base for
    the prompt: the (jurisdiction, tax_type, category) tuples that actually
    have rules, for the jurisdictions in play. Small and stable so it caches
    well and gives the model exactly the categories it may pick from -- not
    the raw rate table (rates are never shown to or set by the model)."""
    rows = (
        (
            await db.execute(
                select(TaxRule.jurisdiction, TaxRule.tax_type, TaxRule.category)
                .where(TaxRule.jurisdiction.in_(jurisdictions))
                .distinct()
            )
        )
        .tuples()
        .all()
    )
    if not rows:
        return "(no tax rules on file for these jurisdictions)"
    lines = sorted(f"- {j} / {t} / {c}" for j, t, c in rows)
    return "\n".join(lines)


def _cache_key(lines: list[LineInput], jurisdictions: list[str], model: str) -> str:
    payload = {
        "model": model,
        "jurisdictions": sorted(jurisdictions),
        "lines": [
            {"i": li.index, "d": li.description, "c": li.context or ""} for li in lines
        ],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_decisions(
    raw: object, known_categories: set[str], line_indexes: set[int]
) -> list[LineTaxDecision]:
    """Enforce Claude's output with pydantic, then re-fit it to our schema:
    coerce any out-of-vocabulary category to "*" and drop decisions for line
    indexes we didn't ask about. This is the "requery to fit the data schema"
    guard -- the model's raw text never reaches the money math unchecked."""
    try:
        parsed = CategorizerResult.model_validate(raw)
    except ValidationError as exc:
        _log.warning(
            "tax categorizer: model output failed validation", extra={"error": str(exc)}
        )
        return []
    out: list[LineTaxDecision] = []
    for d in parsed.decisions:
        if d.line_index not in line_indexes:
            continue
        category = d.category if d.category in known_categories else "*"
        if category != d.category:
            _log.info(
                "tax categorizer: coerced unknown category to catch-all",
                extra={"line_index": d.line_index, "returned": d.category},
            )
        out.append(
            LineTaxDecision(
                line_index=d.line_index,
                category=category,
                taxable=d.taxable,
                rationale=d.rationale,
            )
        )
    return out


_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "line_index": {"type": "integer"},
                    "category": {"type": "string"},
                    "taxable": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
                "required": ["line_index", "category", "taxable", "rationale"],
            },
        }
    },
    "required": ["decisions"],
}


async def _call_claude(
    cfg: AppConfig,
    lines: list[LineInput],
    known_categories: list[str],
    kb_context: str,
) -> object:
    # Imported lazily so the module (and the whole invoice flow) imports fine
    # without the SDK/key present -- only a configured categorizer touches it.
    from anthropic import AsyncAnthropic

    line_block = "\n".join(
        f"[{li.index}] {li.description}"
        + (f"\n     assembly/BoM: {li.context}" if li.context else "")
        for li in lines
    )
    system = (
        "You are a sales-tax and import-duty classification assistant for a "
        "small US business. For each invoice line, choose the single best "
        "tax CATEGORY from the allowed list and decide whether the line is "
        "taxable. You do NOT set rates, jurisdictions, or tax types -- only "
        "the category and taxable flag. If a finished product is assembled "
        "from imported components, classify it by what it is; the components "
        "are separate lines and are classified independently. If nothing "
        'fits, use the catch-all category "*". Always explain your reasoning '
        "in one sentence per line."
    )
    user = (
        "Allowed categories (choose exactly one per line):\n"
        + ", ".join(known_categories)
        + "\n\nKnowledge base coverage (jurisdiction / tax_type / category "
        "tuples that have rules):\n"
        + kb_context
        + "\n\nInvoice lines to classify:\n"
        + line_block
    )
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
    # Adaptive thinking per the claude-api skill; structured output enforces
    # the JSON shape so pydantic validation below always has a well-formed
    # object to check.
    resp = await client.messages.create(
        model=cfg.tax_categorizer_model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


async def categorize_and_price(
    db: AsyncSession,
    cfg: AppConfig,
    *,
    lines: list[LineInput],
    origin_jurisdiction: str,
    destination_jurisdiction: str | None,
) -> list[LinePricing]:
    """Classify each line (Claude, cached + audited), then price it from the
    knowledge base. Returns per-line pricing the caller writes as
    InvoiceLineItemTax rows. If unconfigured, returns [] and the caller keeps
    whatever charges were entered by hand.
    """
    if not is_configured(cfg) or not lines:
        return []

    jurisdictions = [origin_jurisdiction]
    if destination_jurisdiction and destination_jurisdiction != origin_jurisdiction:
        jurisdictions.append(destination_jurisdiction)

    known = await _known_categories(db)
    line_indexes = {li.index for li in lines}
    key = _cache_key(lines, jurisdictions, cfg.tax_categorizer_model)

    now = datetime.now(timezone.utc)
    cached = (
        await db.execute(
            select(TaxCategorizationCache).where(
                TaxCategorizationCache.cache_key == key
            )
        )
    ).scalar_one_or_none()

    decisions: list[LineTaxDecision]
    if cached is not None and cached.expires_at > now:
        decisions = _validate_decisions(
            json.loads(cached.result_json), set(known), line_indexes
        )
    else:
        kb_context = await _kb_context(db, jurisdictions)
        try:
            raw = await _call_claude(cfg, lines, known, kb_context)
        except Exception as exc:  # noqa: BLE001 -- categorizer is best-effort
            _log.warning(
                "tax categorizer: Claude call failed; leaving line taxes as-is",
                extra={"error": str(exc)},
            )
            return []
        decisions = _validate_decisions(raw, set(known), line_indexes)
        # Persist the AUDITED decision (model id + rationale + timestamp) as
        # both the cache and the audit record. Upsert by cache_key.
        payload = CategorizerResult(decisions=decisions).model_dump_json()
        expires = now + timedelta(seconds=cfg.tax_categorizer_cache_ttl_seconds)
        if cached is not None:
            cached.result_json = payload
            cached.model = cfg.tax_categorizer_model
            cached.expires_at = expires
        else:
            db.add(
                TaxCategorizationCache(
                    cache_key=key,
                    result_json=payload,
                    model=cfg.tax_categorizer_model,
                    expires_at=expires,
                )
            )
        await db.flush()
        _log.info(
            "tax categorizer: classified lines",
            extra={"lines": len(lines), "model": cfg.tax_categorizer_model},
        )

    # Price each decision deterministically from the knowledge base. Batch:
    # load every in-effect rule for the jurisdictions in play in ONE query,
    # index it in memory, and resolve per line without more round trips
    # (instead of a lookup_rate query per line x jurisdiction x tax_type).
    resolve = await _load_rate_index(db, jurisdictions, now)
    pricing: list[LinePricing] = []
    by_index = {d.line_index: d for d in decisions}
    for li in lines:
        d = by_index.get(li.index)
        if d is None:
            continue
        charges: list[TaxCharge] = []
        if d.taxable:
            for jur in jurisdictions:
                for tax_type, rate in resolve(jur, d.category):
                    if rate > 0:
                        charges.append(
                            TaxCharge(tax_type=tax_type, jurisdiction=jur, rate=rate)
                        )
        pricing.append(
            LinePricing(
                line_index=li.index,
                category=d.category,
                taxable=d.taxable,
                rationale=d.rationale,
                charges=charges,
            )
        )
    return pricing


def _load_rate_index_from_rules(
    rules: list[TaxRule],
):
    """Build an in-memory resolver from a batch of in-effect rules. For a
    (jurisdiction, category) it yields (tax_type, rate) for each tax type,
    preferring an exact-category rule over the "*" catch-all and the most
    recent effective_from on ties -- the same precedence as
    knowledge_base.lookup_rate, applied in Python so pricing costs one query."""
    # index[(jurisdiction, tax_type, category)] = (effective_from, rate)
    index: dict[tuple[str, str, str], tuple[datetime, Decimal]] = {}
    tax_types_by_jur: dict[str, set[str]] = {}
    for r in rules:
        tax_types_by_jur.setdefault(r.jurisdiction, set()).add(r.tax_type)
        k = (r.jurisdiction, r.tax_type, r.category)
        prev = index.get(k)
        if prev is None or r.effective_from > prev[0]:
            index[k] = (r.effective_from, r.rate)

    def resolve(jurisdiction: str, category: str) -> list[tuple[str, Decimal]]:
        out: list[tuple[str, Decimal]] = []
        for tax_type in sorted(tax_types_by_jur.get(jurisdiction, set())):
            exact = index.get((jurisdiction, tax_type, category))
            star = index.get((jurisdiction, tax_type, "*"))
            chosen = exact or star
            if chosen is not None:
                out.append((tax_type, chosen[1]))
        return out

    return resolve


async def _load_rate_index(db: AsyncSession, jurisdictions: list[str], at: datetime):
    from sqlalchemy import or_

    rules = (
        (
            await db.execute(
                select(TaxRule).where(
                    TaxRule.jurisdiction.in_(jurisdictions),
                    TaxRule.effective_from <= at,
                    or_(TaxRule.effective_to.is_(None), TaxRule.effective_to > at),
                )
            )
        )
        .scalars()
        .all()
    )
    return _load_rate_index_from_rules(list(rules))
