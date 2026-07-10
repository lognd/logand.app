from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from logand_backend.scripts.fetch_tax_rules import RuleInput


def test_rule_input_requires_citation_url() -> None:
    with pytest.raises(ValidationError):
        RuleInput(
            jurisdiction="US-TN",
            tax_type="sales",
            rate=Decimal("0.07"),
            source="TN DOR",
        )  # type: ignore[call-arg]


def test_rule_input_rejects_non_url_citation() -> None:
    with pytest.raises(ValidationError):
        RuleInput(
            jurisdiction="US-TN",
            tax_type="sales",
            rate=Decimal("0.07"),
            source="TN DOR",
            citation_url="not-a-url",
        )


def test_rule_input_requires_non_empty_source() -> None:
    with pytest.raises(ValidationError):
        RuleInput(
            jurisdiction="US-TN",
            tax_type="sales",
            rate=Decimal("0.07"),
            source="",
            citation_url="https://www.tn.gov/",
        )


def test_rule_input_accepts_valid_row() -> None:
    rule = RuleInput(
        jurisdiction="US-TN",
        tax_type="sales",
        rate=Decimal("0.07"),
        source="TN DOR 2026",
        citation_url="https://www.tn.gov/revenue.html",
    )
    assert rule.citation_url == "https://www.tn.gov/revenue.html"
