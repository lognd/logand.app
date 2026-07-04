from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

from logand_backend.app.config import AppConfig
from logand_backend.domain.invoices.export import (
    InvoiceExportData,
    InvoiceLineItemView,
    build_invoice_json,
    build_invoice_plaintext,
)

# Pure-function unit tests for the three export FORMATS built from a
# single InvoiceExportData -- no db, no LaTeX toolchain. Real DB-backed
# loading (load_invoice_export_data) and the actual PDF render
# (generate_invoice_pdf) are exercised by tests/system/test_notifications.py
# and tests/system/test_invoice_pdf_generation.py instead, since those
# need a real session/latexmk respectively.


def _data(**overrides: object) -> InvoiceExportData:
    defaults: dict[str, object] = dict(
        invoice_id=uuid.uuid4(),
        status="sent",
        currency="usd",
        amount_total=Decimal("15.00"),
        due_date=None,
        created_at=date(2026, 1, 1),
        memo=None,
        customer_email="c@example.com",
        line_items=[
            InvoiceLineItemView(
                description="Consulting",
                quantity=Decimal("3"),
                unit="hr",
                unit_price=Decimal("5.00"),
                currency="usd",
            )
        ],
        pay_url="https://logand.app/invoices/x/pay",
    )
    defaults.update(overrides)
    return InvoiceExportData(**defaults)  # type: ignore[arg-type]


def test_line_item_view_computes_line_total() -> None:
    li = InvoiceLineItemView(
        description="Widget",
        quantity=Decimal("4"),
        unit=None,
        unit_price=Decimal("2.50"),
        currency="usd",
    )
    assert li.line_total == Decimal("10.00")


def test_line_item_view_quantizes_to_currency_precision_zero_decimal() -> None:
    """JPY has 0 decimal places -- a fractional yen line total must round
    to a whole number, not a fixed 2dp. See FINDINGS.md L1."""
    li = InvoiceLineItemView(
        description="Widget",
        quantity=Decimal("3"),
        unit=None,
        unit_price=Decimal("1000"),
        currency="jpy",
    )
    assert li.line_total == Decimal("3000")
    assert str(li.line_total) == "3000"


def test_line_item_view_quantizes_to_currency_precision_three_decimal() -> None:
    """BHD has 3 decimal places -- a line total must keep the third
    decimal place instead of being rounded away at 2dp. See
    FINDINGS.md L1."""
    li = InvoiceLineItemView(
        description="Widget",
        quantity=Decimal("2"),
        unit=None,
        unit_price=Decimal("1.005"),
        currency="bhd",
    )
    assert li.line_total == Decimal("2.010")
    assert str(li.line_total) == "2.010"


# -- build_invoice_json ------------------------------------------------------


def test_build_invoice_json_round_trips_core_fields() -> None:
    data = _data()
    payload = json.loads(build_invoice_json(data))

    assert payload["invoice_id"] == str(data.invoice_id)
    assert payload["status"] == "sent"
    assert payload["currency"] == "usd"
    assert payload["amount_total"] == "15.00"
    assert payload["created_at"] == "2026-01-01"
    assert payload["due_date"] is None
    assert payload["pay_url"] == data.pay_url
    assert payload["customer_email"] == "c@example.com"


def test_build_invoice_json_amounts_are_decimal_strings_not_floats() -> None:
    """The whole point of exporting amounts as strings: 0.1 + 0.2 style
    binary-float drift must never leak into a machine-readable invoice
    export that an automated AP tool might sum/reconcile against."""
    data = _data(amount_total=Decimal("19.99"))
    payload = json.loads(build_invoice_json(data))
    assert payload["amount_total"] == "19.99"
    assert isinstance(payload["amount_total"], str)
    li = payload["line_items"][0]
    assert isinstance(li["quantity"], str)
    assert isinstance(li["unit_price"], str)
    assert isinstance(li["line_total"], str)


def test_build_invoice_json_line_items_match_source() -> None:
    data = _data()
    payload = json.loads(build_invoice_json(data))
    (li,) = payload["line_items"]
    assert li["description"] == "Consulting"
    assert li["quantity"] == "3"
    assert li["unit"] == "hr"
    assert li["unit_price"] == "5.00"
    assert li["line_total"] == "15.00"


def test_build_invoice_json_due_date_present_when_set() -> None:
    data = _data(due_date=date(2026, 2, 15))
    payload = json.loads(build_invoice_json(data))
    assert payload["due_date"] == "2026-02-15"


def test_build_invoice_json_is_ascii_and_ends_with_newline() -> None:
    data = _data(memo="non-ascii check: plain text only")
    raw = build_invoice_json(data)
    raw.decode("ascii")  # must not raise -- ensure_ascii=True
    assert raw.endswith(b"\n")


def test_build_invoice_json_survives_curly_braces_in_description() -> None:
    """Regression guard for the .format()-on-assembled-HTML bug found in
    templates.py's _line_items_table -- build_invoice_json never uses
    .format() on already-assembled text, but a literal brace in a
    description must still round-trip losslessly through json.dumps."""
    data = _data(
        line_items=[
            InvoiceLineItemView(
                description="Config {prod} setup",
                quantity=Decimal("1"),
                unit=None,
                unit_price=Decimal("100.00"),
                currency="usd",
            )
        ]
    )
    payload = json.loads(build_invoice_json(data))
    assert payload["line_items"][0]["description"] == "Config {prod} setup"


# -- build_invoice_plaintext --------------------------------------------------


def test_build_invoice_plaintext_includes_core_fields() -> None:
    cfg = AppConfig()
    data = _data()
    text = build_invoice_plaintext(data, cfg)

    assert f"Invoice {data.invoice_id}" in text
    assert "Status: sent" in text
    assert "Date: 2026-01-01" in text
    assert "Consulting" in text
    assert data.pay_url is not None
    assert data.pay_url in text
    assert cfg.invoice_contact_email in text


def test_build_invoice_plaintext_omits_due_date_and_memo_when_absent() -> None:
    cfg = AppConfig()
    data = _data(due_date=None, memo=None)
    text = build_invoice_plaintext(data, cfg)
    assert "Due:" not in text
    assert "Memo:" not in text


def test_build_invoice_plaintext_includes_due_date_and_memo_when_present() -> None:
    cfg = AppConfig()
    data = _data(due_date=date(2026, 3, 1), memo="Thanks for your business")
    text = build_invoice_plaintext(data, cfg)
    assert "Due: 2026-03-01" in text
    assert "Memo: Thanks for your business" in text


def test_build_invoice_plaintext_omits_pay_url_when_not_payable() -> None:
    cfg = AppConfig()
    data = _data(pay_url=None)
    text = build_invoice_plaintext(data, cfg)
    assert "Pay online:" not in text


def test_build_invoice_plaintext_total_matches_amount_total() -> None:
    cfg = AppConfig()
    data = _data(amount_total=Decimal("42.50"))
    text = build_invoice_plaintext(data, cfg)
    assert "42.50 USD" in text


def test_build_invoice_plaintext_columns_stay_aligned() -> None:
    """Regression test: the header row is 40+1+6+1+12+1+12 = 73 chars
    wide, but the divider was 72 dashes and the Total row's amount field
    was one column left of where "Line total" ends above it -- both were
    off by one. Locks in that the divider matches the header's width and
    that "Line total"'s right edge lines up with the Total row's amount."""
    cfg = AppConfig()
    data = _data()
    lines = build_invoice_plaintext(data, cfg).splitlines()

    header = next(line for line in lines if line.startswith("Description"))
    dividers = [line for line in lines if set(line) == {"-"}]
    total_line = next(line for line in lines if line.startswith("Total"))

    assert all(len(d) == len(header) for d in dividers)
    line_total_end = header.index("Line total") + len("Line total")
    # The Total row's amount field is immediately followed by a space and
    # the currency code, so its own right edge is where that space starts.
    amount_end = total_line.index(" USD")
    assert amount_end == line_total_end


def test_build_invoice_plaintext_survives_curly_braces_in_description() -> None:
    """Same regression concern as the JSON test above, applied to the
    plaintext path -- plain string formatting (f-strings/%-less), never
    .format() on text containing the description itself."""
    cfg = AppConfig()
    data = _data(
        line_items=[
            InvoiceLineItemView(
                description="{malformed} braces }{ everywhere {",
                quantity=Decimal("1"),
                unit=None,
                unit_price=Decimal("1.00"),
                currency="usd",
            )
        ]
    )
    text = build_invoice_plaintext(data, cfg)  # must not raise
    assert "{malformed} braces }{ everywhere {" in text
