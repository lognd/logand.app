from __future__ import annotations

import uuid
from decimal import Decimal

from logand_backend.app.config import AppConfig
from logand_backend.domain.invoices.export import InvoiceLineItemView
from logand_backend.domain.notifications import templates

# Pure-function unit tests for the email body builders -- no db, no
# mailer/SMTP, no LaTeX. mailer.py's own shell-wrapping (dark mode,
# footer escaping) is covered separately by tests/unit/test_mailer.py;
# these tests exercise only the content each template returns.


def _cfg(**overrides: object) -> AppConfig:
    return AppConfig(**overrides)  # type: ignore[arg-type]


def _line_item(**overrides: object) -> InvoiceLineItemView:
    defaults: dict[str, object] = dict(
        description="Consulting",
        quantity=Decimal("2"),
        unit="hr",
        unit_price=Decimal("50.00"),
        currency="usd",
    )
    defaults.update(overrides)
    return InvoiceLineItemView(**defaults)  # type: ignore[arg-type]


# -- invoice_sent -------------------------------------------------------------


def test_invoice_sent_includes_order_id_and_breakdown() -> None:
    cfg = _cfg()
    invoice_id = uuid.uuid4()
    subject, html, text = templates.invoice_sent(
        cfg,
        invoice_id=invoice_id,
        amount_total=Decimal("100.00"),
        currency="usd",
        due_date=None,
        line_items=[_line_item()],
    )
    assert str(invoice_id) in html
    assert "Order ID" in html
    assert "Consulting" in html
    assert "Consulting" in text
    assert str(invoice_id) in text


def test_invoice_sent_mentions_attached_pdf_and_plaintext() -> None:
    """The user's explicit "classic 'not rendering correctly?'" request."""
    cfg = _cfg()
    _subject, html, text = templates.invoice_sent(
        cfg,
        invoice_id=uuid.uuid4(),
        amount_total=Decimal("10.00"),
        currency="usd",
        due_date=None,
        line_items=[_line_item()],
    )
    assert "Not rendering correctly?" in html
    assert "PDF and plain-text copy" in html
    assert "Not rendering correctly?" in text
    assert "PDF and plain-text copy" in text


def test_invoice_sent_shows_due_date_when_present() -> None:
    cfg = _cfg()
    _subject, html, _text = templates.invoice_sent(
        cfg,
        invoice_id=uuid.uuid4(),
        amount_total=Decimal("10.00"),
        currency="usd",
        due_date="2026-08-01",
        line_items=[_line_item()],
    )
    assert "2026-08-01" in html


def test_invoice_sent_escapes_line_item_description_in_html() -> None:
    cfg = _cfg()
    _subject, html, _text = templates.invoice_sent(
        cfg,
        invoice_id=uuid.uuid4(),
        amount_total=Decimal("10.00"),
        currency="usd",
        due_date=None,
        line_items=[_line_item(description="<script>alert(1)</script>")],
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_invoice_sent_survives_curly_braces_in_description() -> None:
    """Regression test for a real bug caught during implementation:
    _line_items_table originally left {amount_total} as a literal
    placeholder in its returned HTML and the call site did
    .format(amount_total=amount_total) on it -- since the table string
    already embeds admin-entered, HTML-escaped-but-not-brace-escaped
    description text, a literal "{" or "}" in a real description would
    raise (or silently corrupt) that .format() call. Fixed by making
    amount_total a real function parameter interpolated via f-string.
    This test locks that fix in: it must not raise and the braces must
    survive verbatim (HTML-escaped, but not consumed as a format field).
    """
    cfg = _cfg()
    subject, html, text = templates.invoice_sent(
        cfg,
        invoice_id=uuid.uuid4(),
        amount_total=Decimal("10.00"),
        currency="usd",
        due_date=None,
        line_items=[_line_item(description="Setup {prod} environment")],
    )
    assert subject  # must not raise KeyError/IndexError from .format()
    assert "Setup {prod} environment" in html
    assert "Setup {prod} environment" in text


def test_invoice_sent_total_row_matches_amount_total() -> None:
    cfg = _cfg()
    _subject, html, text = templates.invoice_sent(
        cfg,
        invoice_id=uuid.uuid4(),
        amount_total=Decimal("123.45"),
        currency="usd",
        due_date=None,
        line_items=[_line_item()],
    )
    assert "123.45" in html
    assert "123.45" in text


def test_invoice_sent_text_columns_stay_aligned() -> None:
    """Regression test mirroring test_export.py's plaintext-attachment
    version of the same bug: the header row is 73 chars wide but the
    divider/Total row were off by one, so the email's own text/plain
    body must line up correctly too."""
    cfg = _cfg()
    _subject, _html, text = templates.invoice_sent(
        cfg,
        invoice_id=uuid.uuid4(),
        amount_total=Decimal("1968.00"),
        currency="usd",
        due_date=None,
        line_items=[_line_item()],
    )
    lines = text.splitlines()
    header = next(line for line in lines if line.startswith("Description"))
    dividers = [line for line in lines if set(line) == {"-"}]
    total_line = next(line for line in lines if line.startswith("Total"))

    assert all(len(d) == len(header) for d in dividers)
    line_total_end = header.index("Line total") + len("Line total")
    amount_end = total_line.index(" USD")
    assert amount_end == line_total_end


def test_invoice_sent_no_line_items_renders_empty_table_without_raising() -> None:
    cfg = _cfg()
    subject, html, text = templates.invoice_sent(
        cfg,
        invoice_id=uuid.uuid4(),
        amount_total=Decimal("0.00"),
        currency="usd",
        due_date=None,
        line_items=[],
    )
    assert subject
    assert "<table" in html
    assert text
