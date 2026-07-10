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
_CTA_COLOR = "#66800b"


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

# Matches mailer._LIGHT["muted"] exactly (unlike _TABLE_MUTED_COLOR above,
# which is a separate, lighter tone used only for the line-items table).
# Every `class="ln-muted"` element below needs this set inline -- the
# `.ln-muted` CSS rule only exists inside mailer.py's dark-mode media
# query, so a client honoring light mode (the default everywhere) would
# otherwise render "muted" text at full foreground strength with no
# muting at all.
_MUTED_COLOR = "#665c54"


# The one place this sentence's WORDING is written down. Both the HTML
# and plain-text variants below fill in just the two dynamic fragments
# (the Zelle clause, the contact address) rather than each spelling out
# the surrounding sentence independently -- two copies of the same
# prose is exactly the kind of thing that quietly drifts apart the next
# time only one gets edited. The PDF (pdf/invoice.tex.jinja) and
# customer/Pay.tsx's "Other ways to pay" panel can't literally share
# this Python string (different templating languages), but all three
# are driven from the same `cfg.zelle_handle`/`cfg.invoice_contact_email`
# fields, not independently-typed literals.
_PAYMENT_OPTIONS_TEMPLATE = (
    "Prefer another way to pay? {zelle_clause}PayPal, and in-person "
    "payment by prior arrangement are all accepted -- just email "
    "{contact} to arrange one of these instead."
)


def _zelle_clause(zelle_handle: str | None, *, handle_markup: str = "{handle}") -> str:
    """ "Zelle (<handle>), " when configured, else bare "Zelle, " -- the
    one place that decision is made. `handle_markup` lets a caller wrap
    the handle in its own markup (e.g. HTML `<strong>`) without
    duplicating the surrounding "Zelle (...), "/"Zelle, " punctuation.
    """
    if not zelle_handle:
        return "Zelle, "
    return f"Zelle ({handle_markup.format(handle=zelle_handle)}), "


def _payment_options_html(cfg: AppConfig) -> str:
    """The real alternative-payment-method sentence (Zelle handle, PayPal,
    in person) as actual prose -- not a "see the attached PDF" pointer.
    A customer reading the email on a phone shouldn't have to open a
    second attachment just to learn HOW to pay; the PDF carries the same
    text for the printed/archived copy, but the email is where most
    people actually decide what to do next.
    """
    zelle_clause = _zelle_clause(
        html_escape(cfg.zelle_handle) if cfg.zelle_handle else None,
        handle_markup="<strong>{handle}</strong>",
    )
    contact = html_escape(cfg.invoice_contact_email)
    contact_link = f'<a href="mailto:{contact}" style="color:inherit;">{contact}</a>'
    return _PAYMENT_OPTIONS_TEMPLATE.format(
        zelle_clause=zelle_clause, contact=contact_link
    )


def _payment_options_text(cfg: AppConfig) -> str:
    zelle_clause = _zelle_clause(cfg.zelle_handle)
    return _PAYMENT_OPTIONS_TEMPLATE.format(
        zelle_clause=zelle_clause, contact=cfg.invoice_contact_email
    )


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
        f'<td style="padding:4px 8px; text-align:right;">{li.unit_price_display}</td>'
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
    # 73, not a round number -- matches the exact width of the header row
    # above (40 + 1 + 6 + 1 + 12 + 1 + 12), so the divider spans the full
    # table rather than falling one column short of "Line total"'s edge.
    lines.append("-" * 73)
    for li in line_items:
        unit_suffix = f" ({li.unit})" if li.unit else ""
        lines.append(
            f"{li.description + unit_suffix:<40} {str(li.quantity):>6} "
            f"{str(li.unit_price_display):>12} {str(li.line_total):>12}"
        )
    lines.append("-" * 73)
    return "\n".join(lines)


def invoice_sent(
    cfg: AppConfig,
    *,
    invoice_id: UUID,
    amount_total: Decimal,
    currency: str,
    due_date: str | None,
    line_items: list[InvoiceLineItemView],
    memo: str | None = None,
    pay_url: str | None = None,
    claim_url: str | None = None,
) -> tuple[str, str, str]:
    """Returns (subject, content_html, content_text).

    `pay_url` is caller-supplied (from InvoiceExportData.pay_url) rather
    than derived here, and rendered only when set -- InvoiceExportData
    already suppresses the pay link for invoices that aren't in a
    self-serve-payable state (draft/void/paid/refunded); this template
    must agree with that, not always show a link that would just 409 on
    a future non-"sent" caller. See FINDINGS.md L5.

    `claim_url` (docs/design/16) is set only when this invoice went to a
    "contact" row with no account yet -- rendered as a second CTA above
    the payment paragraph, since claiming the invoice (proving inbox
    control) is the prerequisite to ever seeing/paying it online at all.
    """
    business = html_escape(cfg.invoice_business_name)
    subject = f"Invoice from {cfg.invoice_business_name}"
    due_line = f" (due {due_date})" if due_date else ""
    claim_html = (
        f'<p style="margin:0 0 16px;">{_cta(claim_url, "claim-account --set-password")}'
        "</p>"
        if claim_url
        else ""
    )
    claim_text = (
        f"Claim your account to view/pay online: {claim_url}\n\n" if claim_url else ""
    )

    table_html = _line_items_table(line_items, currency, amount_total)
    memo_html = (
        f'<p class="ln-muted" style="margin:0 0 12px; font-size:12px; '
        f'color:{_MUTED_COLOR};">Memo: {html_escape(memo)}</p>'
        if memo
        else ""
    )
    # One flowing "Payment" paragraph -- the pay-online CTA (if this
    # invoice is in a self-serve-payable state) followed by the real
    # alternative-method sentence, instead of the CTA, a separate "see
    # the PDF" pointer, and a separate attachment footnote as three
    # disconnected one-liners.
    pay_online_html = f"{_cta(pay_url, 'pay-invoice --online')}<br>" if pay_url else ""
    payment_html = (
        f'<p style="margin:16px 0;">{pay_online_html}'
        f'<span class="ln-muted" style="font-size:12px; color:{_MUTED_COLOR};">'
        f"{_payment_options_html(cfg)}</span></p>"
    )
    html = (
        f'<p style="margin:0 0 4px;">You have a new invoice from {business}'
        f"{due_line}.</p>"
        f'<p class="ln-muted" style="margin:0 0 12px; font-size:12px; '
        f'color:{_MUTED_COLOR};">Order ID: {invoice_id}</p>'
        f"{claim_html}"
        f"{table_html}"
        f"{memo_html}"
        f"{payment_html}"
        f'<p class="ln-muted" style="margin:0; font-size:11px; '
        f'color:{_MUTED_COLOR};">'
        "Not rendering correctly? A PDF and plain-text copy of this "
        "invoice are attached."
        "</p>"
    )
    memo_text = f"Memo: {memo}\n\n" if memo else ""
    pay_text = f"Pay online: {pay_url}\n" if pay_url else ""
    text = (
        f"You have a new invoice from {cfg.invoice_business_name}{due_line}.\n"
        f"Order ID: {invoice_id}\n\n"
        f"{claim_text}"
        f"{_line_items_text(line_items, currency)}\n"
        # <60 (not <59) so the amount lands on the same right-hand edge
        # as "Line total" in the header row above -- see export.py's
        # build_invoice_plaintext, which has the identical fix.
        f"{'Total':<60} {amount_total:>12} {currency.upper()}\n\n"
        f"{memo_text}"
        f"{pay_text}"
        f"{_payment_options_text(cfg)}\n\n"
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


def password_reset_requested(
    cfg: AppConfig,
    *,
    reset_url: str,
) -> tuple[str, str, str]:
    """The one-hour link itself is the whole message -- no account detail
    (email, whether one even exists) is echoed back here, since this is
    sent from within the same code path that already refuses to let
    "account exists or not" leak into the HTTP response (see
    domain/auth/password_reset.py::request_password_reset); the email
    body must hold to that same discipline.
    """
    subject = f"Reset your password -- {cfg.invoice_business_name}"
    html = (
        '<p style="margin:0 0 16px;">Someone (hopefully you) requested a '
        "password reset for your account. This link is valid for one "
        "hour and can only be used once.</p>"
        f'<p style="margin:0 0 16px;">{_cta(reset_url, "reset-password")}</p>'
        '<p class="ln-muted" style="margin:0; font-size:12px; '
        f'color:{_MUTED_COLOR};">'
        "If you didn't request this, no action is needed -- your "
        "password hasn't changed and this link will simply expire."
        "</p>"
    )
    text = (
        "Someone (hopefully you) requested a password reset for your "
        "account. This link is valid for one hour and can only be used "
        "once.\n\n"
        f"Reset your password: {reset_url}\n\n"
        "If you didn't request this, no action is needed -- your "
        "password hasn't changed and this link will simply expire.\n"
    )
    return subject, html, text


def email_verification_requested(
    cfg: AppConfig,
    *,
    verify_url: str,
) -> tuple[str, str, str]:
    """docs/design/16 -- sent by register() (and resend-verification) to
    prove inbox control before the account can log in. Mirrors
    password_reset_requested's structure (a single link is the whole
    message) but with a 24-hour window and no "if you didn't request
    this" reassurance -- unlike a reset, an unclicked verify link simply
    leaves the account unable to log in, not a live credential change
    someone else could have triggered.
    """
    subject = f"Verify your email -- {cfg.invoice_business_name}"
    html = (
        '<p style="margin:0 0 16px;">Confirm this email address to finish '
        "setting up your account. This link is valid for 24 hours and can "
        "only be used once.</p>"
        f'<p style="margin:0;">{_cta(verify_url, "verify-email")}</p>'
    )
    text = (
        "Confirm this email address to finish setting up your account. "
        "This link is valid for 24 hours and can only be used once.\n\n"
        f"Verify your email: {verify_url}\n"
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
        f'<p class="ln-muted" style="margin:0; font-size:12px; '
        f'color:{_MUTED_COLOR};">'
        "Review it in your Stripe Dashboard."
        "</p>"
    )
    text = (
        f"A Stripe dispute on invoice {invoice_id} {status_line}.\n\n"
        "Review it in your Stripe Dashboard.\n"
    )
    return subject, html, text
