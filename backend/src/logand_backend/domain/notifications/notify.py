from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Invoice
from logand_backend.db.models.users import User
from logand_backend.domain.notifications import mailer, templates
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

    subject, html, text = templates.invoice_sent(
        cfg,
        invoice_id=invoice.id,
        amount_total=invoice.amount_total,
        currency=invoice.currency,
        due_date=invoice.due_date.isoformat() if invoice.due_date else None,
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
    except Exception:
        _log.error(
            "failed to send invoice-sent notification",
            extra={"invoice_id": str(invoice.id)},
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
        cfg, invoice_id=invoice.id, amount=amount, currency=invoice.currency
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
    except Exception:
        _log.error(
            "failed to send payment-received notification",
            extra={"invoice_id": str(invoice.id)},
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
        except Exception:
            _log.error(
                "failed to send dispute-updated notification",
                extra={"invoice_id": str(invoice.id), "admin_id": str(admin.id)},
            )
