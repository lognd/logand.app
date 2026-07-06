from __future__ import annotations

from decimal import Decimal

from logand_backend.domain.invoices.pdf.renderer import (
    _template_env,
    build_invoice_pdf_data,
    latex_escape,
    latex_escape_lines,
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


def test_latex_escape_lines_preserves_newlines_as_line_breaks() -> None:
    # A bare newline is ordinary whitespace to LaTeX -- passing a
    # multi-line business address through plain latex_escape alone would
    # silently collapse it into one run-on line in the compiled PDF.
    # latex_escape_lines must turn each real newline into an explicit
    # LaTeX line break instead of losing it.
    escaped = latex_escape_lines(
        "123 Main Street\nSpringfield, IL 62704\nEIN: 12-3456789"
    )
    assert escaped == r"123 Main Street\\Springfield, IL 62704\\EIN: 12-3456789"


def test_latex_escape_lines_still_escapes_special_characters_per_line() -> None:
    escaped = latex_escape_lines("100% off\n$5 fee")
    assert escaped == r"100\% off\\\$5 fee"


def test_latex_escape_lines_single_line_matches_plain_escape() -> None:
    assert latex_escape_lines("no newlines here") == latex_escape("no newlines here")


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
        line_items=[
            ("Widget & gadget", Decimal("2"), Decimal("25.00"), Decimal("50.00"), "ea")
        ],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        pay_url=None,
    )

    assert data.memo == r"50\% off \& a \$5 fee"
    assert data.line_items[0].description == r"Widget \& gadget"
    assert data.line_items[0].amount == "50.00"
    assert data.line_items[0].unit == "ea"
    assert data.status == "Sent"


def test_build_invoice_pdf_data_carries_zelle_handle_when_configured() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("50.00"),
        due_date=None,
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        zelle_handle="logan@example.com",
        pay_url=None,
    )
    assert data.zelle_handle == "logan@example.com"


def test_build_invoice_pdf_data_zelle_handle_defaults_to_none() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("50.00"),
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
    assert data.zelle_handle is None


def test_build_invoice_pdf_data_carries_paypal_receive_email_when_configured() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("50.00"),
        due_date=None,
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        paypal_receive_email="pay@example.com",
        pay_url=None,
    )
    assert data.paypal_receive_email == "pay@example.com"


def test_build_invoice_pdf_data_paypal_receive_email_defaults_to_none() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("50.00"),
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
    assert data.paypal_receive_email is None


def test_build_invoice_pdf_data_zero_decimal_currency_has_no_fractional_digits() -> (
    None
):
    """JPY (0dp) -- amounts must render as whole numbers, not a hardcoded
    2dp (e.g. "1000", not "1000.00"). See FINDINGS.md L1."""
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="jpy",
        amount_total=Decimal("3000"),
        due_date=None,
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[("Widget", Decimal("3"), Decimal("1000"), Decimal("3000"), None)],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        pay_url=None,
    )

    assert data.amount_total == "3000"
    assert data.line_items[0].unit_price == "1000"
    assert data.line_items[0].amount == "3000"


def test_build_invoice_pdf_data_three_decimal_currency_keeps_third_digit() -> None:
    """BHD (3dp) -- amounts must keep the third decimal place instead of
    being rounded away at 2dp. See FINDINGS.md L1."""
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="bhd",
        amount_total=Decimal("2.010"),
        due_date=None,
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[("Widget", Decimal("2"), Decimal("1.005"), Decimal("2.010"), None)],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        pay_url=None,
    )

    assert data.amount_total == "2.010"
    assert data.line_items[0].unit_price == "1.005"
    assert data.line_items[0].amount == "2.010"


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
        line_items=[("Widget", Decimal("3"), Decimal("25.00"), Decimal("75.00"), None)],
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
    # No unit given (None -> "") -- the plain "$25.00" branch, not the
    # "$25.00 / <unit>" one.
    assert "/ " not in tex_source.split("Widget")[1].split("\\\\")[0]
    # Balanced braces is a cheap but real sanity check -- a template bug
    # that drops a closing brace on one branch (e.g. the `if memo`
    # conditional) would show up here even without a full LaTeX compile.
    assert tex_source.count("{") == tex_source.count("}")


def test_template_mentions_real_zelle_handle_when_configured() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("75.00"),
        due_date=None,
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        zelle_handle="logan@example.com",
        paypal_receive_email="pay@example.com",
        pay_url=None,
    )
    env = _template_env()
    template = env.get_template("invoice.tex.jinja")
    tex_source = template.render(**data.__dict__)

    # Each configured handle is rendered as a bold method label with the
    # handle set off in monospace (\texttt), distinct from prose -- see the
    # template's own KEEP IN SYNC note tying this to Pay.tsx's font-mono.
    assert r"\textbf{Zelle:}\quad\texttt{logan@example.com}" in tex_source
    assert r"\textbf{PayPal:}\quad\texttt{pay@example.com}" in tex_source
    assert tex_source.count("{") == tex_source.count("}")


def test_template_falls_back_to_bare_zelle_when_not_configured() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("75.00"),
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

    # No handles configured -> bare bold labels (no colon, since the colon
    # only prefixes a handle), no monospace handle set off after them.
    assert r"\textbf{Zelle}" in tex_source
    assert r"\textbf{PayPal}" in tex_source
    assert r"\textbf{In-Person:}" in tex_source
    assert r"\texttt{" not in tex_source
    assert tex_source.count("{") == tex_source.count("}")


def test_template_renders_unit_price_with_unit_suffix() -> None:
    data = build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal("75.00"),
        due_date="2026-08-01",
        created_at="2026-07-01",
        memo=None,
        customer_email="customer@example.com",
        line_items=[
            ("Consulting", Decimal("3"), Decimal("25.00"), Decimal("75.00"), "hr")
        ],
        business_name="logand.app",
        business_details="",
        contact_email="billing@logand.app",
        pay_url=None,
    )
    env = _template_env()
    template = env.get_template("invoice.tex.jinja")
    tex_source = template.render(**data.__dict__)

    assert r"\$25.00 / hr" in tex_source


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

    assert "pay this invoice online" not in tex_source


def _pdf_data_with_tax(subtotal, tax_amount, amount_total):
    return build_invoice_pdf_data(
        invoice_id="abc-123",
        status="sent",
        currency="usd",
        amount_total=Decimal(amount_total),
        subtotal=Decimal(subtotal),
        tax_amount=Decimal(tax_amount),
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


def test_build_invoice_pdf_data_sets_has_tax_when_tax_present() -> None:
    data = _pdf_data_with_tax("480.00", "33.60", "513.60")
    assert data.has_tax is True
    assert data.subtotal == "480.00"
    assert data.tax_amount == "33.60"


def test_build_invoice_pdf_data_no_tax_flag_when_zero() -> None:
    # A zero-tax invoice keeps the single Total row (has_tax False), the same
    # as before the tax feature existed.
    data = _pdf_data_with_tax("480.00", "0.00", "480.00")
    assert data.has_tax is False


def test_template_shows_subtotal_and_tax_rows_when_taxed() -> None:
    data = _pdf_data_with_tax("480.00", "33.60", "513.60")
    env = _template_env()
    tex = env.get_template("invoice.tex.jinja").render(**data.__dict__)
    assert "Subtotal:" in tex
    assert "Tax:" in tex
    assert "480.00" in tex and "33.60" in tex and "513.60" in tex
    assert tex.count("{") == tex.count("}")


def test_template_omits_subtotal_tax_rows_when_no_tax() -> None:
    data = _pdf_data_with_tax("480.00", "0.00", "480.00")
    env = _template_env()
    tex = env.get_template("invoice.tex.jinja").render(**data.__dict__)
    assert "Subtotal:" not in tex
    assert "Tax:" not in tex
