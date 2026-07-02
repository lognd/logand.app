from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import jinja2

from logand_backend.logging import get_logger

_log = get_logger(__name__)

# The `logandinvoice` LaTeX class + Jinja2 template live alongside this
# module (see logandinvoice.cls and invoice.tex.jinja) -- both need to be
# on latexmk's TEXINPUTS when compiling, which render_invoice_pdf sets
# from _PDF_DIR below rather than assuming a working directory.
_PDF_DIR = Path(__file__).parent

# Already LaTeX-safe literals, not raw symbols -- these get interpolated
# into the template directly, unescaped by latex_escape (they're not
# user/admin-entered text, they're this module's own fixed data). "$"
# specifically MUST stay escaped here: LaTeX's math-mode toggle, an
# unescaped one breaks the compile by leaving math mode open for the rest
# of the document (confirmed against a real compile failure -- "Runaway
# argument? File ended while scanning" is exactly what an unbalanced $
# looks like).
_CURRENCY_SYMBOLS = {"usd": r"\$", "eur": "€", "gbp": "£"}


def _currency_symbol(currency: str) -> str:
    # Falls back to the currency code itself (LaTeX-safe: ISO currency
    # codes are plain ASCII letters, nothing that needs escaping) rather
    # than guessing at a symbol for a currency this map doesn't know --
    # "42.00 XYZ" is honest; a wrong guessed symbol would just be wrong.
    return _CURRENCY_SYMBOLS.get(currency.lower(), currency.upper() + " ")


# LaTeX's special characters, escaped one character at a time (not via
# sequential str.replace calls) -- a sequential-replace approach has to
# carefully order which character it escapes first (get backslash wrong
# and a LATER replacement's own inserted backslashes get re-escaped), a
# single per-character pass sidesteps that whole class of bug entirely.
_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "%": r"\%",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(value: object) -> str:
    """Escapes arbitrary text (customer names, memos, line-item
    descriptions -- anything that isn't literal LaTeX source this module
    wrote itself) for safe interpolation into a .tex file. Every field in
    InvoicePdfData/InvoiceLineItemData that ultimately comes from user- or
    admin-entered data MUST be escaped through this before reaching the
    template -- an unescaped $, &, or backslash from, say, an invoice memo
    would otherwise either break the LaTeX compile or (worse) let entered
    text inject arbitrary LaTeX commands into a legal/financial document.
    """
    return "".join(_LATEX_SPECIAL_CHARS.get(ch, ch) for ch in str(value))


@dataclass(frozen=True)
class InvoiceLineItemData:
    description: str
    quantity: str
    unit_price: str
    amount: str
    # Already LaTeX-escaped, empty string (not None) when there isn't
    # one -- the template can then just always render "\VAR{unit_price}
    # / \VAR{unit}" style text without a None-check of its own.
    unit: str


@dataclass(frozen=True)
class InvoicePdfData:
    invoice_number: str
    invoice_date: str
    due_date: str
    status: str
    bill_to: str
    business_name: str
    business_details: str
    currency_upper: str
    currency_symbol: str
    amount_total: str
    line_items: list[InvoiceLineItemData]
    contact_email: str
    pay_url: str | None = None
    memo: str | None = None


def build_invoice_pdf_data(
    *,
    invoice_id: str,
    status: str,
    currency: str,
    amount_total: Decimal,
    due_date: str | None,
    created_at: str,
    memo: str | None,
    customer_email: str,
    line_items: list[tuple[str, Decimal, Decimal, str | None]],
    business_name: str,
    business_details: str,
    contact_email: str,
    pay_url: str | None,
) -> InvoicePdfData:
    """Assembles + LaTeX-escapes everything the template needs from raw
    domain values -- the one chokepoint every field passes through, so
    escaping is applied exactly once, in one well-tested place, rather
    than trusted to happen (or be remembered) at each call site.

    `invoice_id` is used as the human-facing invoice number as-is (a UUID)
    -- there's no separate sequential invoice-numbering scheme yet (see
    domain/invoices/service.py's TODO if one gets added later); a UUID is
    at least unique and unambiguous in the meantime, just not the neat
    incrementing "INV-0001" a formal accounting system would use.
    """
    line_item_data = [
        InvoiceLineItemData(
            description=latex_escape(description),
            quantity=latex_escape(str(quantity)),
            unit_price=latex_escape(f"{unit_price:.2f}"),
            amount=latex_escape(f"{(quantity * unit_price):.2f}"),
            unit=latex_escape(unit) if unit else "",
        )
        for description, quantity, unit_price, unit in line_items
    ]
    return InvoicePdfData(
        invoice_number=latex_escape(invoice_id),
        invoice_date=latex_escape(created_at),
        due_date=latex_escape(due_date or "Upon receipt"),
        status=latex_escape(status.capitalize()),
        bill_to=latex_escape(customer_email),
        business_name=latex_escape(business_name),
        business_details=latex_escape(business_details),
        currency_upper=latex_escape(currency.upper()),
        currency_symbol=_currency_symbol(currency),
        amount_total=latex_escape(f"{amount_total:.2f}"),
        line_items=line_item_data,
        contact_email=latex_escape(contact_email),
        pay_url=pay_url,
        memo=latex_escape(memo) if memo else None,
    )


def _template_env() -> jinja2.Environment:
    # Custom delimiters (\VAR{}, \BLOCK{}) instead of Jinja2's default
    # {{ }}/{% %} -- LaTeX itself uses `{`/`}`/`%` constantly, so the
    # default Jinja2 syntax would collide with real LaTeX source
    # throughout the template. This is the standard documented pattern
    # for templating LaTeX with Jinja2, not a one-off workaround.
    return jinja2.Environment(
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        loader=jinja2.FileSystemLoader(str(_PDF_DIR)),
    )


class PdfRenderError(RuntimeError):
    """Raised when latexmk fails to compile the generated .tex source.
    Carries the compiler's own log output -- essential for diagnosing a
    real compile failure (a bad escape, a missing package), not just
    "something went wrong."""

    def __init__(self, message: str, log: str) -> None:
        super().__init__(message)
        self.log = log


def render_invoice_pdf(data: InvoicePdfData) -> bytes:
    """Renders the Jinja2 .tex template with `data`, compiles it with
    latexmk, and returns the resulting PDF's bytes. Requires a LaTeX
    toolchain (latexmk + the packages logandinvoice.cls RequirePackage's --
    see backend/Dockerfile) to actually be installed; there is no pure-
    Python fallback, by design (see this package's module doc comment on
    why LaTeX was chosen over WeasyPrint for this specific requirement).
    """
    env = _template_env()
    template = env.get_template("invoice.tex.jinja")
    tex_source = template.render(**data.__dict__)

    with tempfile.TemporaryDirectory(prefix="logand-invoice-pdf-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        tex_path = tmp_path / "invoice.tex"
        tex_path.write_text(tex_source, encoding="utf-8")

        result = subprocess.run(
            [
                "latexmk",
                "-pdf",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={tmp_dir}",
                str(tex_path),
            ],
            cwd=tmp_dir,
            # {**os.environ, ...}, NOT a bare {"TEXINPUTS": ...} -- passing
            # `env=` at all REPLACES the subprocess's entire environment
            # rather than extending it, which silently wiped out PATH too
            # (confirmed via a real container run: latexmk couldn't even
            # find pdflatex on the search path anymore). logandinvoice.cls
            # lives in _PDF_DIR, not the temp compile dir -- TEXINPUTS
            # (trailing colon means "plus LaTeX's own normal search path")
            # is what latexmk uses to find it.
            env={**os.environ, "TEXINPUTS": f"{_PDF_DIR}:"},
            capture_output=True,
            text=True,
        )

        pdf_path = tmp_path / "invoice.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            # Full latexmk log captured on PdfRenderError.log AND logged
            # here -- this is exactly the failure task #68 diagnosed by
            # hand against a real environment; it should never again
            # require re-running the compile manually to see why it broke.
            _log.error(
                "invoice PDF compile failed",
                extra={
                    "invoice_number": data.invoice_number,
                    "returncode": result.returncode,
                    "latexmk_log": (result.stdout + result.stderr)[-4000:],
                },
            )
            raise PdfRenderError(
                "latexmk failed to compile invoice PDF",
                log=result.stdout + result.stderr,
            )
        return pdf_path.read_bytes()
