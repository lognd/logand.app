from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Invoice, InvoiceLineItem
from logand_backend.db.models.users import User
from logand_backend.domain.invoices.pdf.renderer import (
    build_invoice_pdf_data,
    render_invoice_pdf,
)
from logand_backend.errors import InvoiceError

# Lives here (not domain/invoices/service.py) specifically so
# domain/notifications/notify.py can import generate_invoice_pdf/
# build_invoice_json/build_invoice_plaintext without a circular import --
# service.py already imports FROM notify.py (notify_payment_received), so
# notify.py importing something FROM service.py would close a cycle. Every
# export FORMAT (PDF, the invoice-sent email's HTML/plaintext breakdown,
# the for-robots.json attachment) is built from the exact same
# InvoiceExportData, loaded once by load_invoice_export_data -- one query,
# reused by every format, instead of each format re-deriving line items/
# customer/pay_url independently and risking one of them silently
# drifting out of sync with what the others show.


@dataclass(frozen=True)
class InvoiceLineItemView:
    description: str
    quantity: Decimal
    unit: str | None
    unit_price: Decimal

    @property
    def line_total(self) -> Decimal:
        return self.quantity * self.unit_price


@dataclass(frozen=True)
class InvoiceExportData:
    invoice_id: UUID
    status: str
    currency: str
    amount_total: Decimal
    due_date: date | None
    created_at: date
    memo: str | None
    customer_email: str
    line_items: list[InvoiceLineItemView]
    # None when the invoice isn't in a self-serve-payable state (draft/
    # void/paid/refunded) -- a "pay online" link on a PDF/email for an
    # invoice that would just 409 on that route is misleading, not merely
    # unhelpful, per docs/design/04.
    pay_url: str | None


async def load_invoice_export_data(
    db: AsyncSession, invoice_id: UUID, cfg: AppConfig
) -> InvoiceExportData | None:
    """None means "no such invoice" (missing or soft-deleted) -- callers
    treat that as InvoiceError.NotFound; kept as a plain None here rather
    than a Result since this is a private-ish loader, not a public
    domain entry point with its own error-handling contract.
    """
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or invoice.deleted_at is not None:
        return None

    line_items = (
        (
            await db.execute(
                select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
            )
        )
        .scalars()
        .all()
    )
    customer = await db.get(User, invoice.customer_id)
    customer_email = customer.email if customer is not None else "unknown"

    return InvoiceExportData(
        invoice_id=invoice.id,
        status=invoice.status,
        currency=invoice.currency,
        amount_total=invoice.amount_total,
        due_date=invoice.due_date,
        created_at=invoice.created_at.date(),
        memo=invoice.memo,
        customer_email=customer_email,
        line_items=[
            InvoiceLineItemView(
                description=li.description,
                quantity=li.quantity,
                unit=li.unit,
                unit_price=li.unit_price,
            )
            for li in line_items
        ],
        pay_url=(
            f"{cfg.public_base_url}/invoices/{invoice.id}/pay"
            if invoice.status in ("sent", "overdue")
            else None
        ),
    )


async def generate_invoice_pdf(
    db: AsyncSession, invoice_id: UUID, cfg: AppConfig
) -> Result[bytes, InvoiceError]:
    """Renders a professional, printable PDF for the given invoice (see
    domain/invoices/pdf/ for the LaTeX class/template/renderer this calls
    into). Shared by both the customer-facing and admin PDF download
    routes AND the invoice-sent email's PDF attachment -- ownership/role
    checks belong at each caller (this function doesn't take a requesting
    user at all), this only knows how to build the PDF once an
    invoice_id has already been authorized.
    """
    data = await load_invoice_export_data(db, invoice_id, cfg)
    if data is None:
        return Err(InvoiceError.NotFound)

    pdf_data = build_invoice_pdf_data(
        invoice_id=str(data.invoice_id),
        status=data.status,
        currency=data.currency,
        amount_total=data.amount_total,
        due_date=data.due_date.isoformat() if data.due_date else None,
        created_at=data.created_at.isoformat(),
        memo=data.memo,
        customer_email=data.customer_email,
        line_items=[
            (li.description, li.quantity, li.unit_price, li.unit)
            for li in data.line_items
        ],
        business_name=cfg.invoice_business_name,
        business_details=cfg.invoice_business_details,
        contact_email=cfg.invoice_contact_email,
        pay_url=data.pay_url,
    )
    # render_invoice_pdf shells out to latexmk -- real (if brief) CPU/IO
    # work that would otherwise block the event loop for every other
    # concurrent request while one PDF compiles.
    pdf_bytes = await asyncio.to_thread(render_invoice_pdf, pdf_data)
    return Ok(pdf_bytes)


def build_invoice_json(data: InvoiceExportData) -> bytes:
    """ "for-robots.json" -- a machine-readable export of the exact same
    invoice an admin/customer sees rendered in the PDF and the email
    body, for whatever automated tool a customer's own AP system wants
    to point at it (amounts as decimal STRINGS, never float, so nothing
    downstream silently loses cents to binary floating-point rounding).
    """
    payload = {
        "invoice_id": str(data.invoice_id),
        "status": data.status,
        "currency": data.currency,
        "amount_total": str(data.amount_total),
        "due_date": data.due_date.isoformat() if data.due_date else None,
        "created_at": data.created_at.isoformat(),
        "memo": data.memo,
        "customer_email": data.customer_email,
        "pay_url": data.pay_url,
        "line_items": [
            {
                "description": li.description,
                "quantity": str(li.quantity),
                "unit": li.unit,
                "unit_price": str(li.unit_price),
                "line_total": str(li.line_total),
            }
            for li in data.line_items
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"


def build_invoice_plaintext(data: InvoiceExportData, cfg: AppConfig) -> str:
    """A real attached .txt file (distinct from the multipart/alternative
    text/plain BODY every email already has) -- a fixed-width, terminal-
    style itemized breakdown for a recipient whose mail client can't
    render the HTML card at all, or who just wants a plain copy to
    grep/archive. Column widths are fixed, not measured against the
    actual data, so this never needs updating for a longer description;
    a description that overflows its column just runs long rather than
    breaking alignment for the amount columns after it.
    """
    lines: list[str] = []
    lines.append(f"Invoice {data.invoice_id}")
    lines.append(f"Status: {data.status}")
    lines.append(f"Date: {data.created_at.isoformat()}")
    if data.due_date:
        lines.append(f"Due: {data.due_date.isoformat()}")
    if data.memo:
        lines.append(f"Memo: {data.memo}")
    lines.append("")
    lines.append(
        f"{'Description':<40} {'Qty':>6} {'Unit price':>12} {'Line total':>12}"
    )
    lines.append("-" * 72)
    for li in data.line_items:
        unit_suffix = f" / {li.unit}" if li.unit else ""
        lines.append(
            f"{li.description:<40} {str(li.quantity):>6} "
            f"{f'{li.unit_price}{unit_suffix}':>12} {str(li.line_total):>12}"
        )
    lines.append("-" * 72)
    lines.append(f"{'Total':<59} {str(data.amount_total):>12} {data.currency.upper()}")
    lines.append("")
    if data.pay_url:
        lines.append(f"Pay online: {data.pay_url}")
    lines.append(f"Questions: {cfg.invoice_contact_email}")
    return "\n".join(lines) + "\n"
