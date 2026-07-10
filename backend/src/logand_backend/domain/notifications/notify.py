from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Invoice
from logand_backend.db.models.users import User
from logand_backend.domain.auth.email_verification import mint_email_verification_token
from logand_backend.domain.invoices.export import (
    build_invoice_json,
    build_invoice_plaintext,
    generate_invoice_pdf,
    load_invoice_export_data,
)
from logand_backend.domain.invoices.pdf.renderer import PdfRenderError
from logand_backend.domain.notifications import mailer, templates
from logand_backend.domain.payments.currency import quantize_to_currency
from logand_backend.logging import get_logger

_log = get_logger(__name__)

# Best-effort, never blocking or failing the caller's actual transaction --
# an invoice still gets sent, a payment still gets recorded, even if the
# customer's mail server is down or SMTP isn't configured at all. Every
# function here swallows send failures (logged, not raised) for exactly
# that reason: email is a notification about something that already
# happened, not a precondition for it happening.


async def notify_invoice_sent(
    db: AsyncSession, cfg: AppConfig, invoice: Invoice
) -> None:
    if not mailer.is_configured(cfg):
        return
    customer = await db.get(User, invoice.customer_id)
    if customer is None or customer.emails_opted_out:
        return

    # Everything below is best-effort against an invoice that is already
    # committed as "sent" -- a transient failure here (e.g. a DB error
    # loading export data) must be logged and swallowed, never raised,
    # or the caller's /send route would 500 for an operation that
    # already succeeded (see FINDINGS.md M2).
    try:
        export_data = await load_invoice_export_data(db, invoice.id, cfg)
        if export_data is None:
            # Invoice vanished (soft-deleted) between the caller's commit
            # and here -- nothing left to notify about.
            return

        # docs/design/16: when the recipient is a contact row (no account
        # yet -- password_hash IS NULL), mint a 'claim' token alongside the
        # invoice and include the claim link in the same email. This is
        # the ONLY place a 'claim' token gets minted -- there is no
        # self-serve "resend claim link" the way 'verify' has
        # resend-verification, so this re-mints on every subsequent
        # invoice sent to the same still-unclaimed contact.
        claim_url: str | None = None
        if customer.password_hash is None:
            raw_claim_token = await mint_email_verification_token(
                db, customer.id, "claim"
            )
            await db.flush()
            claim_url = f"{cfg.public_base_url}/claim?token={raw_claim_token}"

        subject, html, text = templates.invoice_sent(
            cfg,
            invoice_id=invoice.id,
            # export_data.amount_total_display (not the raw invoice.amount_
            # total column value) -- the column always round-trips at its
            # full Numeric(14,3) storage scale regardless of the
            # currency's real precision. See FINDINGS.md L1.
            amount_total=export_data.amount_total_display,
            currency=invoice.currency,
            due_date=invoice.due_date.isoformat() if invoice.due_date else None,
            line_items=export_data.line_items,
            memo=export_data.memo,
            pay_url=export_data.pay_url,
            claim_url=claim_url,
        )

        attachments: list[mailer.EmailAttachment] = []
        # Best-effort: the email still carries the full HTML/plaintext
        # breakdown even if PDF generation fails -- a PDF-less invoice
        # email is degraded, not useless, and must never 500 the whole
        # /send route. generate_invoice_pdf can return
        # Err(InvoiceError) (invoice vanished), raise PdfRenderError (a
        # LaTeX compile failure with a log to inspect), or raise
        # something else entirely (e.g. FileNotFoundError if latexmk
        # itself isn't on PATH) -- all three are swallowed here.
        try:
            pdf_result = await generate_invoice_pdf(
                db, invoice.id, cfg, export_data=export_data
            )
        except PdfRenderError as exc:
            _log.warning(
                "invoice PDF rendering failed for invoice-sent notification",
                extra={"invoice_id": str(invoice.id), "log": exc.log},
            )
        except Exception as exc:
            _log.error(
                "unexpected error generating invoice PDF for invoice-sent notification",
                extra={"invoice_id": str(invoice.id)},
                exc_info=exc,
            )
        else:
            if pdf_result.is_err:
                _log.warning(
                    "failed to generate invoice PDF for invoice-sent notification",
                    extra={
                        "invoice_id": str(invoice.id),
                        "error": str(pdf_result.danger_err),
                    },
                )
            else:
                attachments.append(
                    mailer.EmailAttachment(
                        filename=f"invoice-{invoice.id}.pdf",
                        content=pdf_result.danger_ok,
                        maintype="application",
                        subtype="pdf",
                    )
                )
        attachments.append(
            mailer.EmailAttachment(
                filename=f"invoice-{invoice.id}.txt",
                content=build_invoice_plaintext(export_data, cfg).encode("utf-8"),
                maintype="text",
                subtype="plain",
            )
        )
        # Must be the LAST attachment -- a human skimming the attachment
        # list should see the PDF/plaintext copies before the
        # machine-readable one.
        attachments.append(
            mailer.EmailAttachment(
                filename="for-robots.json",
                content=build_invoice_json(export_data),
                maintype="application",
                subtype="json",
            )
        )

        await mailer.send_email(
            cfg,
            to_email=customer.email,
            to_user_id=customer.id,
            subject=subject,
            content_html=html,
            content_text=text,
            attachments=tuple(attachments),
        )
    except Exception as exc:
        _log.error(
            "failed to send invoice-sent notification",
            extra={"invoice_id": str(invoice.id)},
            exc_info=exc,
        )


async def notify_payment_received(
    db: AsyncSession, cfg: AppConfig, invoice: Invoice, amount: Decimal
) -> None:
    if not mailer.is_configured(cfg):
        return
    customer = await db.get(User, invoice.customer_id)
    if customer is None or customer.emails_opted_out:
        return

    subject, html, text = templates.payment_received(
        cfg,
        invoice_id=invoice.id,
        amount=quantize_to_currency(amount, invoice.currency),
        currency=invoice.currency,
    )
    try:
        await mailer.send_email(
            cfg,
            to_email=customer.email,
            to_user_id=customer.id,
            subject=subject,
            content_html=html,
            content_text=text,
        )
    except Exception as exc:
        _log.error(
            "failed to send payment-received notification",
            extra={"invoice_id": str(invoice.id)},
            exc_info=exc,
        )


async def notify_refund_settled(
    db: AsyncSession, cfg: AppConfig, invoice: Invoice, amount: Decimal
) -> None:
    """A refund that settled asynchronously (charge.refund.updated
    transitioning a "pending" Refund to "succeeded") is otherwise
    invisible to the customer -- unlike a synchronous refund, which the
    admin who issued it can already see confirmed in the response, an
    async settlement has no other signal (see L3 in FINDINGS.md)."""
    if not mailer.is_configured(cfg):
        return
    customer = await db.get(User, invoice.customer_id)
    if customer is None or customer.emails_opted_out:
        return

    subject, html, text = templates.refund_settled(
        cfg,
        invoice_id=invoice.id,
        amount=quantize_to_currency(amount, invoice.currency),
        currency=invoice.currency,
    )
    try:
        await mailer.send_email(
            cfg,
            to_email=customer.email,
            to_user_id=customer.id,
            subject=subject,
            content_html=html,
            content_text=text,
        )
    except Exception as exc:
        _log.error(
            "failed to send refund-settled notification",
            extra={"invoice_id": str(invoice.id)},
            exc_info=exc,
        )


async def notify_dispute_updated(
    db: AsyncSession, cfg: AppConfig, invoice: Invoice, dispute_status: str
) -> None:
    """Admin-facing, not customer-facing -- unlike every other notify_*
    here, this goes to every admin account (opt-out still respected;
    CAN-SPAM's opt-out right applies to any account, admin or not), not
    the invoice's customer. A dispute needs a human to act on it (submit
    evidence before Stripe's deadline, or just know a chargeback landed),
    and there's no in-app admin notification center to check instead.
    """
    if not mailer.is_configured(cfg):
        return

    subject, html, text = templates.dispute_updated(
        cfg, invoice_id=invoice.id, dispute_status=dispute_status
    )
    admins = (
        (
            await db.execute(
                select(User).where(
                    User.role == "admin",
                    User.emails_opted_out.is_(False),
                    User.disabled_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for admin in admins:
        try:
            await mailer.send_email(
                cfg,
                to_email=admin.email,
                to_user_id=admin.id,
                subject=subject,
                content_html=html,
                content_text=text,
            )
        except Exception as exc:
            _log.error(
                "failed to send dispute-updated notification",
                extra={"invoice_id": str(invoice.id), "admin_id": str(admin.id)},
                exc_info=exc,
            )


async def notify_password_reset_requested(
    cfg: AppConfig, *, to_email: str, to_user_id: UUID, reset_url: str
) -> None:
    """Deliberately does NOT check `emails_opted_out` -- unlike every
    other notify_* here, this is a security-critical transactional email
    the recipient just explicitly triggered by submitting the forgot-
    password form themselves, not a marketing/informational send CAN-
    SPAM's opt-out right is meant to cover. Takes email/user_id/reset_url
    directly rather than a User row + db session, since the caller
    (api/auth.py) already has both from
    domain.auth.password_reset.request_password_reset's return value --
    no reason to re-fetch here.
    """
    if not mailer.is_configured(cfg):
        return

    subject, html, text = templates.password_reset_requested(cfg, reset_url=reset_url)
    try:
        await mailer.send_email(
            cfg,
            to_email=to_email,
            to_user_id=to_user_id,
            subject=subject,
            content_html=html,
            content_text=text,
        )
    except Exception as exc:
        # critical, not error (see FINDINGS.md L2): this fires from a
        # BackgroundTask, after the response already told the user "a
        # reset link was sent" -- there is no other signal to the user
        # or to us that the send failed, and the token silently expires
        # unused. Bumped severity + an explicit alertable=True marker so
        # this is distinguishable from routine notify_* send failures in
        # alerting/log-search, since this one blocks a security action.
        _log.critical(
            "failed to send password-reset-requested notification",
            extra={"user_id": str(to_user_id), "alertable": True},
            exc_info=exc,
        )


async def notify_email_verification_requested(
    cfg: AppConfig, *, to_email: str, to_user_id: UUID, verify_url: str
) -> None:
    """Mirrors notify_password_reset_requested exactly (docs/design/16):
    deliberately does NOT check emails_opted_out (this is a security/
    account-setup email the recipient just triggered themselves by
    registering, not a marketing send), and takes email/user_id/verify_url
    directly rather than a User + db session since the caller (api/auth.py)
    already has both from domain.auth.service.register's return value.
    """
    if not mailer.is_configured(cfg):
        return

    subject, html, text = templates.email_verification_requested(
        cfg, verify_url=verify_url
    )
    try:
        await mailer.send_email(
            cfg,
            to_email=to_email,
            to_user_id=to_user_id,
            subject=subject,
            content_html=html,
            content_text=text,
        )
    except Exception as exc:
        # critical, not error -- same reasoning as
        # notify_password_reset_requested: this fires after the response
        # already told the registrant "check your email," and there is no
        # other signal to them or to us that the send failed.
        _log.critical(
            "failed to send email-verification-requested notification",
            extra={"user_id": str(to_user_id), "alertable": True},
            exc_info=exc,
        )
