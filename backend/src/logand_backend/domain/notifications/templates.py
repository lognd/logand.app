from __future__ import annotations

from decimal import Decimal
from html import escape as html_escape
from uuid import UUID

from logand_backend.app.config import AppConfig

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
        f'<a href="{url}" class="ln-cta" '
        f'style="color:{_CTA_COLOR}; text-decoration:none; font-weight:600;">'
        f"$ {html_escape(label)}</a>"
    )


def invoice_sent(
    cfg: AppConfig,
    *,
    invoice_id: UUID,
    amount_total: Decimal,
    currency: str,
    due_date: str | None,
) -> tuple[str, str, str]:
    """Returns (subject, content_html, content_text)."""
    pay_url = f"{cfg.public_base_url}/invoices/{invoice_id}/pay"
    business = html_escape(cfg.invoice_business_name)
    subject = f"Invoice from {cfg.invoice_business_name}"
    due_line = f" (due {due_date})" if due_date else ""

    html = (
        f'<p style="margin:0 0 16px;">You have a new invoice from {business} '
        f"for <strong>{amount_total} {currency.upper()}</strong>"
        f"{due_line}.</p>"
        f'<p style="margin:0 0 16px;">{_cta(pay_url, "pay-invoice --online")}</p>'
        '<p class="ln-muted" style="margin:0; font-size:12px;">'
        "Or use one of the other payment methods listed on the invoice PDF."
        "</p>"
    )
    text = (
        f"You have a new invoice from {cfg.invoice_business_name} for "
        f"{amount_total} {currency.upper()}{due_line}.\n\n"
        f"Pay online: {pay_url}\n"
        "Other payment methods are listed on the invoice PDF.\n"
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
        f"<strong>{amount} {currency.upper()}</strong> for invoice "
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
        f"<strong>{amount} {currency.upper()}</strong> for invoice "
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
    }.get(dispute_status, dispute_status)
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
