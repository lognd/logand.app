from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from logand_backend.db.models.tax import TaxRule
from logand_backend.domain.invoices.tax.categorizer import (
    _load_rate_index_from_rules,
    _validate_decisions,
)


def _rule(jur, ttype, cat, rate, eff_from):
    return TaxRule(
        jurisdiction=jur,
        tax_type=ttype,
        category=cat,
        rate=Decimal(rate),
        effective_from=eff_from,
    )


def test_validate_decisions_coerces_unknown_category_to_catchall() -> None:
    raw = {
        "decisions": [
            {"line_index": 0, "category": "made-up", "taxable": True, "rationale": "x"}
        ]
    }
    out = _validate_decisions(raw, {"tangible-goods", "*"}, {0})
    assert len(out) == 1
    # An out-of-vocabulary category is never trusted -- it becomes the "*"
    # catch-all so the money math only ever prices known categories.
    assert out[0].category == "*"
    assert out[0].taxable is True


def test_validate_decisions_drops_unrequested_line_indexes() -> None:
    raw = {
        "decisions": [
            {"line_index": 0, "category": "*", "taxable": True, "rationale": ""},
            {"line_index": 99, "category": "*", "taxable": True, "rationale": ""},
        ]
    }
    out = _validate_decisions(raw, {"*"}, {0})
    assert [d.line_index for d in out] == [0]


def test_validate_decisions_returns_empty_on_malformed_output() -> None:
    # Not even the right shape -- pydantic rejects it and the caller gets [],
    # which means "no categorizer charges" (fall back to admin-entered ones).
    assert _validate_decisions({"nope": 1}, {"*"}, {0}) == []


def test_rate_index_prefers_exact_category_over_catchall() -> None:
    now = datetime.now(timezone.utc)
    resolve = _load_rate_index_from_rules(
        [
            _rule("US-TN", "sales", "*", "0.07", now),
            _rule("US-TN", "sales", "tangible-goods", "0.0925", now),
        ]
    )
    # tangible-goods has its own rule -> 9.25%; anything else -> the 7% "*".
    assert resolve("US-TN", "tangible-goods") == [("sales", Decimal("0.0925"))]
    assert resolve("US-TN", "service") == [("sales", Decimal("0.07"))]


def test_rate_index_prefers_newest_effective_from() -> None:
    now = datetime.now(timezone.utc)
    older = now - timedelta(days=365)
    resolve = _load_rate_index_from_rules(
        [
            _rule("US-TN", "sales", "*", "0.07", older),
            _rule("US-TN", "sales", "*", "0.08", now),
        ]
    )
    assert resolve("US-TN", "service") == [("sales", Decimal("0.08"))]


def test_rate_index_emits_every_tax_type_for_a_jurisdiction() -> None:
    now = datetime.now(timezone.utc)
    resolve = _load_rate_index_from_rules(
        [
            _rule("US-customs", "import_duty", "imported-component", "0.02", now),
            _rule("US-TN", "sales", "*", "0.07", now),
        ]
    )
    assert resolve("US-customs", "imported-component") == [
        ("import_duty", Decimal("0.02"))
    ]
