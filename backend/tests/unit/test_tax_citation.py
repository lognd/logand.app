from __future__ import annotations

import pytest

from logand_backend.domain.invoices.tax.citation import (
    assert_government_citation,
    is_government_source,
)

_ALLOWED = ["floridarevenue.com"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tn.gov/revenue.html",
        "http://revenue.wi.gov/",
        "https://portal.ct.gov/DRS",
        "https://tax.utah.gov/",
        "https://tax.state.co.us/",
        "https://www.defense.mil/tax",
        "https://floridarevenue.com/pages/default.aspx",
        "https://sub.floridarevenue.com/foo",
    ],
)
def test_is_government_source_accepts_gov_mil_us_and_allowlist(url: str) -> None:
    assert is_government_source(url, _ALLOWED) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://www.example.com",
        "https://taxjar.com/rates",
        "not a url",
        "ftp://revenue.tn.gov/",
        "",
    ],
)
def test_is_government_source_rejects_non_government(url: str) -> None:
    assert is_government_source(url, _ALLOWED) is False


def test_assert_government_citation_raises_with_clear_message() -> None:
    with pytest.raises(ValueError, match="not a recognized government source"):
        assert_government_citation("https://example.com", _ALLOWED)


def test_assert_government_citation_passes_for_gov_url() -> None:
    assert_government_citation("https://www.tn.gov/revenue.html", _ALLOWED)
