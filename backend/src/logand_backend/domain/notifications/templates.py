from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from logand_backend.app.config import AppConfig

# Valid, minimal semantic HTML (real <html>/<body>/<p>/<a> structure, no
# div-soup) -- "professional and parsable by others' automated tools" was
# an explicit requirement; mailer.build_message wraps this content in the
# outer <html><body> and appends the CAN-SPAM footer, so these functions
# only own the message-specific content, not the envelope.


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
    subject = f"Invoice from {cfg.invoice_business_name}"
    due_line = f" (due {due_date})" if due_date else ""

    html = (
        f"<p>You have a new invoice from {cfg.invoice_business_name} for "
        f"{amount_total} {currency.upper()}{due_line}.</p>"
        f'<p><a href="{pay_url}">Pay this invoice online</a>, or use one of '
        "the other payment methods listed on the invoice PDF.</p>"
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
        f"<p>We received your payment of {amount} {currency.upper()} for "
        f"invoice {invoice_id}. Thank you.</p>"
        f'<p><a href="{invoices_url}">View your invoices</a>.</p>'
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
        f"<p>Your refund of {amount} {currency.upper()} for invoice "
        f"{invoice_id} has been processed.</p>"
        f'<p><a href="{invoices_url}">View your invoices</a>.</p>'
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
        f"<p>A Stripe dispute on invoice {invoice_id} {status_line}.</p>"
        "<p>Review it in your Stripe Dashboard.</p>"
    )
    text = (
        f"A Stripe dispute on invoice {invoice_id} {status_line}.\n\n"
        "Review it in your Stripe Dashboard.\n"
    )
    return subject, html, text
