from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from logand_backend.scripts.fetch_tax_rules import _parse_hts_file


def test_parse_hts_file_csv_free_percent_and_skips_compound(tmp_path: Path) -> None:
    csv_text = (
        "hts8,brief_description,general_rate_of_duty\n"
        "8471.30.01,Portable computers,Free\n"
        "8542.31.00,Integrated circuits,2.6%\n"
        '0402.10.10,Milk powder,"3.3 cents/kg + 3%"\n'
    )
    path = tmp_path / "hts.csv"
    path.write_text(csv_text)

    rules = _parse_hts_file(path, year="2026")

    by_code = {r.category: r for r in rules}
    assert set(by_code) == {"8471.30.01", "8542.31.00"}

    free_rule = by_code["8471.30.01"]
    assert free_rule.rate == Decimal(0)
    assert free_rule.jurisdiction == "US-customs"
    assert free_rule.tax_type == "import_duty"
    assert free_rule.source == "USITC HTS 2026"

    pct_rule = by_code["8542.31.00"]
    assert pct_rule.rate == Decimal("0.026")


def test_parse_hts_file_json(tmp_path: Path) -> None:
    rows = [
        {"hts_number": "9503.00.00", "general rate of duty": "Free"},
        {"hts_number": "6109.10.00", "general rate of duty": "16.5%"},
    ]
    path = tmp_path / "hts.json"
    path.write_text(json.dumps(rows))

    rules = _parse_hts_file(path)
    by_code = {r.category: r for r in rules}
    assert by_code["9503.00.00"].rate == Decimal(0)
    assert by_code["6109.10.00"].rate == Decimal("0.165")


def test_parse_hts_file_skips_row_missing_code(tmp_path: Path) -> None:
    csv_text = "hts8,general_rate_of_duty\n,Free\n8471.30.01,Free\n"
    path = tmp_path / "hts.csv"
    path.write_text(csv_text)

    rules = _parse_hts_file(path)
    assert [r.category for r in rules] == ["8471.30.01"]
