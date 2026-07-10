from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.models.tax import TaxRule
from logand_backend.domain.invoices.tax import classification_store
from logand_backend.logging import get_logger

# Phase 4/5 (docs/design/16-sales-tax.md): the "do-as-we-go" Claude
# categorizer.
#
# Flow: for each invoice line, look up the item in the per-item classification
# store (classification_store). Items seen before -- whether confirmed by a
# human or a prior pending Claude result -- are reused with NO model call.
# Only genuinely-new items are sent to Claude, batched into ONE call, and
# stored as `pending` for a human to confirm/override later.
#
# Division of authority (the audit story):
#   - Claude ONLY classifies an item into a category that exists in the
#     knowledge base, decides taxable yes/no, and (for imports) proposes an
#     HTS code. It never invents a rate.
#   - Its output is enforced with pydantic and re-fit to the DB's category
#     vocabulary; an out-of-vocabulary category is coerced to "*".
#   - Rates come from the deterministic knowledge base (one batched query).
#   - A human decision (confirmed/overridden) always outranks the model and
#     is never re-asked.
#
# Resilience: rate limits and other Claude failures degrade gracefully -- the
# new item is simply left unclassified (no charges) and gets retried the next
# time it's invoiced, rather than failing invoice creation.

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
    # HS/HTS code for an imported item (drives import duty); empty otherwise.
    hts_code: str = Field(default="")
    # The model's own justification -- persisted for audit, never used in the
    # money math.
    rationale: str = Field(default="")


class CategorizerResult(BaseModel):
    model_config = {"frozen": True}

    decisions: list[LineTaxDecision]


# Sales tax is SINGLE-SOURCE per line (see docs/design/16-sales-tax.md "Sales-
# tax sourcing"): a line carries at most ONE `sales` charge, destination-
# preferred then origin. Every OTHER tax_type (import_duty, use, ...) still
# stacks normally across jurisdictions.
_SALES_TAX_TYPE = "sales"


@dataclass(frozen=True)
class TaxCharge:
    tax_type: str
    jurisdiction: str
    rate: Decimal


@dataclass(frozen=True)
class LinePricing:
    """What the caller turns into InvoiceLineItemTax rows: the audited
    category/taxable decision plus the deterministically-priced charges.
    `pending` flags a fresh Claude classification not yet human-confirmed."""

    line_index: int
    category: str
    taxable: bool
    hts_code: str | None
    pending: bool
    charges: list[TaxCharge]


async def _known_categories(db: AsyncSession) -> list[str]:
    """The category vocabulary Claude is allowed to choose from -- distinct
    categories present in tax_rules, plus the "*" catch-all."""
    rows = (await db.execute(select(TaxRule.category).distinct())).scalars().all()
    cats = {c for c in rows if c and c != "*"}
    cats.add("*")
    return sorted(cats)


async def _kb_context(db: AsyncSession, jurisdictions: list[str]) -> str:
    """A compact snapshot of the relevant knowledge base for the prompt: the
    (jurisdiction, tax_type, category) tuples that have rules. Small and
    deterministic so it caches well; rates are never shown to the model."""
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
    return "\n".join(sorted(f"- {j} / {t} / {c}" for j, t, c in rows))


def _validate_decisions(
    raw: object, known_categories: set[str], line_indexes: set[int]
) -> list[LineTaxDecision]:
    """Enforce Claude's output with pydantic, then re-fit it to our schema:
    coerce any out-of-vocabulary category to "*" and drop decisions for line
    indexes we didn't ask about. The model's raw text never reaches the money
    math unchecked."""
    try:
        parsed = CategorizerResult.model_validate(raw)
    except ValidationError as exc:
        _log.warning(
            "tax categorizer: model output failed validation",
            extra={"error": str(exc)},
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
                hts_code=d.hts_code,
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
                    "hts_code": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "line_index",
                    "category",
                    "taxable",
                    "hts_code",
                    "rationale",
                ],
            },
        }
    },
    "required": ["decisions"],
}


class RateLimited(Exception):
    """Raised internally when Claude rate-limits us, so the caller can defer
    the unclassified items instead of failing the invoice."""


async def _call_claude(
    cfg: AppConfig,
    lines: list[LineInput],
    known_categories: list[str],
    kb_context: str,
) -> object:
    # Imported lazily so the module (and the whole invoice flow) imports fine
    # without the SDK/key present -- only a configured categorizer touches it.
    import anthropic
    from anthropic import AsyncAnthropic

    line_block = "\n".join(
        f"[{li.index}] {li.description}"
        + (f"\n     assembly/BoM: {li.context}" if li.context else "")
        for li in lines
    )
    system = (
        "You are a sales-tax and import-duty classification assistant for a "
        "small US business. For each invoice line, choose the single best tax "
        "CATEGORY from the allowed list, decide whether the line is taxable, "
        "and -- only if the item is physically imported -- give the 6-10 digit "
        "HTS (Harmonized Tariff Schedule) code; otherwise leave hts_code empty. "
        "You do NOT set rates, jurisdictions, or tax types. If a finished "
        "product is assembled from imported components, classify it by what it "
        'is; the components are separate lines. If nothing fits, use "*". '
        "Explain your reasoning in one sentence per line."
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
    # The SDK already retries 429/5xx with exponential backoff (default
    # max_retries=2); a RateLimitError that survives that is surfaced so the
    # caller can defer rather than fail. max_retries bumped a bit for a
    # background-ish classification path.
    client = AsyncAnthropic(api_key=cfg.anthropic_api_key, max_retries=4)
    try:
        resp = await client.messages.create(
            model=cfg.tax_categorizer_model,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.RateLimitError as exc:
        raise RateLimited() from exc
    import json

    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


def _load_rate_index_from_rules(rules: list[TaxRule]):
    """Build an in-memory resolver from a batch of in-effect rules. For a
    (jurisdiction, category) it yields (tax_type, rate), preferring an exact-
    category rule over the "*" catch-all and the most recent effective_from --
    the same precedence as knowledge_base.lookup_rate, in Python so pricing
    costs one query."""
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
            chosen = index.get((jurisdiction, tax_type, category)) or index.get(
                (jurisdiction, tax_type, "*")
            )
            if chosen is not None:
                out.append((tax_type, chosen[1]))
        return out

    return resolve


async def _load_rate_index(db: AsyncSession, jurisdictions: list[str], at: datetime):
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


def _resolve_sales_charge(
    resolve,
    origin_jurisdiction: str,
    destination_jurisdiction: str | None,
    category: str,
) -> TaxCharge | None:
    """Pick the ONE `sales` charge for a line -- single-source, destination-
    preferred (docs/design/16-sales-tax.md "Sales-tax sourcing").

    US sales-tax sourcing genuinely varies by state and nexus (origin- vs
    destination-based); this app deliberately encodes ONE simplified rule
    rather than per-state law: if the customer's destination jurisdiction has
    a configured `sales` rule for the category, that jurisdiction sources the
    charge; otherwise the seller's origin jurisdiction does; otherwise there
    is no sales charge. The OPERATOR must confirm this matches their real
    nexus/registration obligations with an accountant.

    Presence of a configured `sales` rule -- not its rate -- decides sourcing:
    a destination with a 0% rule still sources the (zero) charge here and does
    not fall through to origin.
    """
    for jurisdiction in (destination_jurisdiction, origin_jurisdiction):
        if not jurisdiction:
            continue
        for tax_type, rate in resolve(jurisdiction, category):
            if tax_type != _SALES_TAX_TYPE:
                continue
            # This jurisdiction is the single source; a 0 rate means a
            # configured-but-untaxed sale, still no fall-through to origin.
            if rate > 0:
                return TaxCharge(
                    tax_type=_SALES_TAX_TYPE, jurisdiction=jurisdiction, rate=rate
                )
            return None
    return None


def _all_jurisdictions(
    origin_jurisdiction: str,
    destination_jurisdiction: str | None,
    extra_jurisdictions: list[str] | None,
) -> list[str]:
    """Union of origin, destination, and any extras (e.g. "US-customs" for
    import duty), in order, de-duplicated -- shared by the classification
    (kb_context) and pricing passes so both ever see the exact same set."""
    jurisdictions = [origin_jurisdiction]
    for jur in [destination_jurisdiction, *(extra_jurisdictions or [])]:
        if jur and jur not in jurisdictions:
            jurisdictions.append(jur)
    return jurisdictions


async def categorize_and_price(
    db: AsyncSession,
    cfg: AppConfig,
    *,
    lines: list[LineInput],
    origin_jurisdiction: str,
    destination_jurisdiction: str | None,
    extra_jurisdictions: list[str] | None = None,
) -> list[LinePricing]:
    """Classify each line (per-item cache first, Claude only for new items),
    then price from the knowledge base. Returns per-line pricing the caller
    writes as InvoiceLineItemTax rows. Unconfigured / rate-limited / unknown
    lines return no charges (retried next time).

    `extra_jurisdictions` lets a caller price additional jurisdictions
    alongside origin/destination in the SAME batched Claude call and the
    same batched knowledge-base query -- e.g. "US-customs" for import duty,
    which applies regardless of the customer's own destination state.
    """
    if not lines:
        return []

    now = datetime.now(timezone.utc)
    keys = {
        li.index: classification_store.normalize_key(li.description) for li in lines
    }
    stored = await classification_store.get_many(db, sorted(set(keys.values())))

    # New items = ones with no stored classification. Only these hit Claude.
    unknown = [li for li in lines if keys[li.index] not in stored]
    if unknown and is_configured(cfg):
        known_cats = await _known_categories(db)
        line_indexes = {li.index for li in unknown}
        jurisdictions = _all_jurisdictions(
            origin_jurisdiction, destination_jurisdiction, extra_jurisdictions
        )
        kb_context = await _kb_context(db, jurisdictions)
        try:
            raw = await _call_claude(cfg, unknown, known_cats, kb_context)
        except RateLimited:
            _log.warning(
                "tax categorizer: rate-limited; deferring new items",
                extra={"deferred": len(unknown)},
            )
            raw = None
        except Exception as exc:  # noqa: BLE001 -- best-effort classification
            _log.warning(
                "tax categorizer: Claude call failed; deferring new items",
                extra={"error": str(exc)},
            )
            raw = None
        if raw is not None:
            decisions = _validate_decisions(raw, set(known_cats), line_indexes)
            by_idx = {d.line_index: d for d in decisions}
            for li in unknown:
                d = by_idx.get(li.index)
                if d is None:
                    continue
                row = await classification_store.upsert_pending(
                    db,
                    key=keys[li.index],
                    description=li.description,
                    category=d.category,
                    taxable=d.taxable,
                    hts_code=d.hts_code or None,
                    model=cfg.tax_categorizer_model,
                    rationale=d.rationale,
                )
                stored[keys[li.index]] = row
            _log.info(
                "tax categorizer: classified new items",
                extra={"count": len(decisions), "model": cfg.tax_categorizer_model},
            )

    # Price every line that now has a classification, from one batched
    # knowledge-base query.
    jurisdictions = _all_jurisdictions(
        origin_jurisdiction, destination_jurisdiction, extra_jurisdictions
    )
    resolve = await _load_rate_index(db, jurisdictions, now)

    pricing: list[LinePricing] = []
    for li in lines:
        row = stored.get(keys[li.index])
        if row is None:
            continue  # still unclassified (unconfigured / deferred) -> no charges
        charges: list[TaxCharge] = []
        if row.taxable:
            # Non-sales taxes (import_duty, use, ...) stack across EVERY
            # jurisdiction. Sales tax is single-source and handled separately
            # below so a line can never carry two `sales` charges (e.g. an
            # origin-state AND a destination-state sales charge summing).
            for jur in jurisdictions:
                for tax_type, rate in resolve(jur, row.category):
                    if tax_type == _SALES_TAX_TYPE:
                        continue
                    if rate > 0:
                        charges.append(
                            TaxCharge(tax_type=tax_type, jurisdiction=jur, rate=rate)
                        )
            # The single sales charge -- destination-preferred, else origin.
            sales_charge = _resolve_sales_charge(
                resolve,
                origin_jurisdiction,
                destination_jurisdiction,
                row.category,
            )
            if sales_charge is not None:
                charges.append(sales_charge)
        pricing.append(
            LinePricing(
                line_index=li.index,
                category=row.category,
                taxable=row.taxable,
                hts_code=row.hts_code,
                pending=row.status == "pending",
                charges=charges,
            )
        )
    return pricing
