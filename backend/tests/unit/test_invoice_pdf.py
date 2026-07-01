from __future__ import annotations

from decimal import Decimal

from logand_backend.domain.invoices.pdf.renderer import (
    _template_env,
    build_invoice_pdf_data,
    latex_escape,
)


def test_latex_escape_handles_every_special_character() -> None:
    # One string containing every character LaTeX treats specially --
    # a wrong escape (or a missed one) here would either break every
    # invoice PDF that happened to contain that character, or silently
    # let it through as raw LaTeX source.
    raw = r"100% & $5 fee_note {braces} ~tilde ^caret \backslash # hash"
    escaped = latex_escape(raw)

    assert r"\%" in escaped
    assert r"\&" in escaped
    assert r"\$" in escaped
    assert r"\_" in escaped
    assert r"\{" in escaped
    assert r"\}" in escaped
    assert r"\textasciitilde{}" in escaped
    assert r"\textasciicircum{}" in escaped
    assert r"\textbackslash{}" in escaped
    assert r"\#" in escaped


def test_latex_escape_leaves_plain_text_untouched() -> None:
    assert latex_escape("Consulting services") == "Consulting services"
    assert latex_escape("") == ""


def test_latex_escape_handles_non_string_input() -> None:
    # Decimal/int values (quantities, prices) get str()'d first -- this is
    # what makes it safe to call latex_escape on those directly rather
    # than requiring every call site to str() first.
    assert latex_escape(Decimal("10.00")) == "10.00"
    assert latex_escape(42) == "42"


def test_build_invoice_pdf_data_escapes_every_free_text_field() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("50.00"),
        due_date="2026-08-01",
        created_at="2026-07-01",
        memo="50% off & a $5 fee",
        customer_email="customer@example.com",
        line_items=[("Widget & gadget", Decimal("2"), Decimal("25.00"))],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        pay_url=None,
    )

    assert data.memo == r"50\% off \& a \$5 fee"
    assert data.line_items[0].description == r"Widget \& gadget"
    assert data.line_items[0].amount == "50.00"
    assert data.status == "Sent"


def test_build_invoice_pdf_data_defaults_due_date_when_absent() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="draft",
        currency="usd",
        amount_total=Decimal("0.00"),
        due_date=None,
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        pay_url=None,
    )

    assert data.due_date == "Upon receipt"
    assert data.memo is None
    assert data.pay_url is None


def test_build_invoice_pdf_data_unknown_currency_falls_back_to_code() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="cad",
        amount_total=Decimal("10.00"),
        due_date=None,
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        pay_url=None,
    )

    # "CAD " (code + trailing space), not a guessed/wrong symbol -- see
    # _currency_symbol's own doc comment on why an honest fallback beats a
    # wrong guess.
    assert data.currency_symbol == "CAD "


def test_template_renders_without_compiling() -> None:
    """Confirms the Jinja2 template itself renders (variable substitution,
    the line-items loop, conditional pay_url/memo blocks) without
    requiring an actual LaTeX toolchain -- render_invoice_pdf's own
    compile step is covered separately by a system test that skips
    cleanly where latexmk isn't installed (see
    tests/system/test_invoice_pdf_generation.py).
    """
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("75.00"),
        due_date="2026-08-01",
        created_at="2026-07-01",
        memo="Net 30",
        customer_email="customer@example.com",
        line_items=[("Widget", Decimal("3"), Decimal("25.00"))],
        business_name="logand.app",
        business_details="123 Example St",
        contact_email="billing@logand.app",
        pay_url="https://logand.app/invoices/abc-123/pay",
    )
    env = _template_env()
    template = env.get_template("invoice.tex.jinja")
    tex_source = template.render(**data.__dict__)

    assert r"\documentclass{logandinvoice}" in tex_source
    assert "Widget" in tex_source
    assert r"\href{https://logand.app/invoices/abc-123/pay}" in tex_source
    assert "Net 30" in tex_source
    # Balanced braces is a cheap but real sanity check -- a template bug
    # that drops a closing brace on one branch (e.g. the `if memo`
    # conditional) would show up here even without a full LaTeX compile.
    assert tex_source.count("{") == tex_source.count("}")


def test_template_omits_pay_online_line_when_pay_url_is_none() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="draft",
        currency="usd",
        amount_total=Decimal("0.00"),
        due_date=None,
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        pay_url=None,
    )
    env = _template_env()
    template = env.get_template("invoice.tex.jinja")
    tex_source = template.render(**data.__dict__)

    assert "Pay online" not in tex_source
