from __future__ import annotations

from decimal import Decimal
from html import escape as html_escape
from uuid import UUID

from logand_backend.app.config import AppConfig
from logand_backend.domain.invoices.export import InvoiceLineItemView

# Valid, minimal semantic HTML (real <p>/<a> structure, no div-soup) --
# "professional and parsable by others' automated tools" was an explicit
# requirement; mailer.build_message wraps this content in the shared
# light/dark terminal-window shell (mailer._wrap_terminal_shell) and
# appends the CAN-SPAM footer, so these functions only own the message-
# specific content, not the envelope or its styling. The one styling
# concern that DOES belong here is the CTA link's `class="ln-cta"` +
# inline accent-green color -- that pairing is what makes it read as a
# terminal prompt/command rather than a generic blue hyperlink, and is
# specific to what each message is actually asking the reader to do.

# Matches mailer._LIGHT["accent_green"] -- inline so the CTA still reads
# correctly in a mail client that ignores class-based dark-mode overrides
# (the .ln-cta class in the shell's <style> block still repaints it for
# dark mode wherever that IS honored).
_CTA_COLOR = "#79740e"


def _cta(url: str, label: str) -> str:
    """A `$ <command>`-styled call-to-action link -- reads as a terminal
    prompt invoking a command, matching the site's own TerminalWindow
    aesthetic (frontend/src/app/routes/public/TerminalWindow.tsx colors
    its own prompt lines the same accent-green). `text-decoration:none`
    plus the monospace inheritance from the shell's `.ln-text` wrapper is
    what sells it as a command rather than a normal link.
    """
    return (
        f'<a href="{html_escape(url, quote=True)}" class="ln-cta" '
        f'style="color:{_CTA_COLOR}; text-decoration:none; font-weight:600;">'
        f"$ {html_escape(label)}</a>"
    )


# Matches mailer._LIGHT["border"]/["muted"] -- inline for the same reason
# _CTA_COLOR is: a mail client that ignores the shell's dark-mode <style>
# block entirely still gets a correctly-colored (light-mode) table rather
# than an unstyled one.
_TABLE_BORDER_COLOR = "#d5c4a1"
_TABLE_MUTED_COLOR = "#7c6f64"


def _line_items_table(
    line_items: list[InvoiceLineItemView], currency: str, amount_total: Decimal
) -> str:
    """A real order-id + line-item breakdown -- description/quantity/
    unit price/line total per row, then a total row -- instead of just
    the bare invoice total the email used to show. `description`/`unit`
    are admin-entered free text, not attacker-controlled from a customer
    form, but get the same escaping discipline as everything else on
    this path (see FINDINGS.md's audit of this feature).

    `amount_total` is a real function parameter, not interpolated via a
    later `.format()` call on the assembled HTML -- `.format()` on a
    string that already embeds admin-entered description text would
    raise (or worse, silently misbehave) the moment that text ever
    contains a literal "{" or "}", since html.escape does not escape
    curly braces.
    """
    currency_label = html_escape(currency.upper())
    rows = "".join(
        '<tr><td style="padding:4px 8px 4px 0; text-align:left;">'
        f"{html_escape(li.description)}"
        f"{f' ({html_escape(li.unit)})' if li.unit else ''}"
        "</td>"
        f'<td style="padding:4px 8px; text-align:right;">{li.quantity}</td>'
        f'<td style="padding:4px 8px; text-align:right;">{li.unit_price}</td>'
        f'<td style="padding:4px 0 4px 8px; text-align:right;">'
        f"{li.line_total}</td></tr>"
        for li in line_items
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" '
        f'style="margin:12px 0; font-size:13px; border-collapse:collapse;">'
        f'<tr style="color:{_TABLE_MUTED_COLOR}; '
        f'border-bottom:1px solid {_TABLE_BORDER_COLOR};">'
        '<th style="padding:4px 8px 4px 0; text-align:left; font-weight:400;">'
        "Description</th>"
        '<th style="padding:4px 8px; text-align:right; font-weight:400;">Qty</th>'
        '<th style="padding:4px 8px; text-align:right; font-weight:400;">'
        "Unit price</th>"
        '<th style="padding:4px 0 4px 8px; text-align:right; font-weight:400;">'
        "Line total</th></tr>"
        f"{rows}"
        f'<tr style="border-top:1px solid {_TABLE_BORDER_COLOR}; font-weight:600;">'
        f'<td colspan="3" style="padding:6px 8px 0 0; text-align:right;">Total</td>'
        f'<td style="padding:6px 0 0 8px; text-align:right;">'
        f"{amount_total} {currency_label}</td></tr>"
        "</table>"
    )


def _line_items_text(line_items: list[InvoiceLineItemView], currency: str) -> str:
    lines = [f"{'Description':<40} {'Qty':>6} {'Unit price':>12} {'Line total':>12}"]
    lines.append("-" * 72)
    for li in line_items:
        unit_suffix = f" ({li.unit})" if li.unit else ""
        lines.append(
            f"{li.description + unit_suffix:<40} {str(li.quantity):>6} "
            f"{str(li.unit_price):>12} {str(li.line_total):>12}"
        )
    lines.append("-" * 72)
    return "\n".join(lines)


def invoice_sent(
    cfg: AppConfig,
    *,
    invoice_id: UUID,
    amount_total: Decimal,
    currency: str,
    due_date: str | None,
    line_items: list[InvoiceLineItemView],
) -> tuple[str, str, str]:
    """Returns (subject, content_html, content_text)."""
    pay_url = f"{cfg.public_base_url}/invoices/{invoice_id}/pay"
    business = html_escape(cfg.invoice_business_name)
    subject = f"Invoice from {cfg.invoice_business_name}"
    due_line = f" (due {due_date})" if due_date else ""

    table_html = _line_items_table(line_items, currency, amount_total)
    html = (
        f'<p style="margin:0 0 4px;">You have a new invoice from {business}'
        f"{due_line}.</p>"
        f'<p class="ln-muted" style="margin:0; font-size:12px;">'
        f"Order ID: {invoice_id}</p>"
        f"{table_html}"
        f'<p style="margin:16px 0;">{_cta(pay_url, "pay-invoice --online")}</p>'
        '<p class="ln-muted" style="margin:0 0 16px; font-size:12px;">'
        "Or use one of the other payment methods listed on the invoice PDF."
        "</p>"
        '<p class="ln-muted" style="margin:0; font-size:11px;">'
        "Not rendering correctly? A PDF and plain-text copy of this "
        "invoice are attached."
        "</p>"
    )
    text = (
        f"You have a new invoice from {cfg.invoice_business_name}{due_line}.\n"
        f"Order ID: {invoice_id}\n\n"
        f"{_line_items_text(line_items, currency)}\n"
        f"{'Total':<59} {amount_total:>12} {currency.upper()}\n\n"
        f"Pay online: {pay_url}\n"
        "Other payment methods are listed on the invoice PDF.\n\n"
        "Not rendering correctly? A PDF and plain-text copy of this "
        "invoice are attached.\n"
    )
    return subject, html, text


def payment_received(
    cfg: AppConfig,
    *,
    invoice_id: UUID,
    amount: Decimal,
    currency: str,
) -> tuple[str, str, str]:
    subject = f"Payment received -- {cfg.invoice_business_name}"
    invoices_url = f"{cfg.public_base_url}/invoices"

    html = (
        f'<p style="margin:0 0 16px;">We received your payment of '
        f"<strong>{amount} {html_escape(currency.upper())}</strong> for invoice "
        f"{invoice_id}. Thank you.</p>"
        f'<p style="margin:0;">{_cta(invoices_url, "view-invoices")}</p>'
    )
    text = (
        f"We received your payment of {amount} {currency.upper()} for "
        f"invoice {invoice_id}. Thank you.\n\n"
        f"View your invoices: {invoices_url}\n"
    )
    return subject, html, text


def refund_settled(
    cfg: AppConfig,
    *,
    invoice_id: UUID,
    amount: Decimal,
    currency: str,
) -> tuple[str, str, str]:
    subject = f"Refund processed -- {cfg.invoice_business_name}"
    invoices_url = f"{cfg.public_base_url}/invoices"

    html = (
        f'<p style="margin:0 0 16px;">Your refund of '
        f"<strong>{amount} {html_escape(currency.upper())}</strong> for invoice "
        f"{invoice_id} has been processed.</p>"
        f'<p style="margin:0;">{_cta(invoices_url, "view-invoices")}</p>'
    )
    text = (
        f"Your refund of {amount} {currency.upper()} for "
        f"invoice {invoice_id} has been processed.\n\n"
        f"View your invoices: {invoices_url}\n"
    )
    return subject, html, text


def dispute_updated(
    cfg: AppConfig,
    *,
    invoice_id: UUID,
    dispute_status: str,
) -> tuple[str, str, str]:
    """Admin-facing (not customer-facing, unlike the other two templates
    above) -- see notify.notify_dispute_updated's own doc comment."""
    status_line = {
        "needs_response": "needs a response before Stripe's deadline",
        "under_review": "is under review by the cardholder's bank",
        "won": "was resolved in your favor",
        "lost": "was lost -- funds have been withdrawn",
    }.get(dispute_status, html_escape(dispute_status))
    subject = f"Stripe dispute update -- invoice {invoice_id}"

    html = (
        f'<p style="margin:0 0 16px;">A Stripe dispute on invoice '
        f"{invoice_id} {status_line}.</p>"
        '<p class="ln-muted" style="margin:0; font-size:12px;">'
        "Review it in your Stripe Dashboard."
        "</p>"
    )
    text = (
        f"A Stripe dispute on invoice {invoice_id} {status_line}.\n\n"
        "Review it in your Stripe Dashboard.\n"
    )
    return subject, html, text
