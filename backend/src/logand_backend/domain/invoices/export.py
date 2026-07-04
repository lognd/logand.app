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
from logand_backend.domain.payments.currency import quantize_to_currency
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
    # Needed so line_total can quantize to THIS currency's real precision
    # (0dp for JPY/KRW/..., 3dp for BHD/KWD/..., 2dp otherwise) rather than
    # a hardcoded 2dp -- see FINDINGS.md L1. Every currency stored on an
    # invoice line item is the parent invoice's own currency (there is no
    # per-line currency), so this is always InvoiceExportData.currency.
    currency: str

    @property
    def line_total(self) -> Decimal:
        # Quantized to the currency's real precision so every export
        # format (PDF, email, .txt, for-robots.json) agrees on the same
        # rounded figure -- quantity is Numeric(10,3) and unit_price is
        # Numeric(12,3), so their raw product can carry more decimal
        # places than the currency actually uses; leaving it unrounded (or
        # rounded to a fixed 2dp regardless of currency) let the PDF
        # (which used to format with :.2f) silently disagree with every
        # other format, and let the visible rows fail to sum to
        # amount_total (also stored at the currency's real precision).
        # See FINDINGS.md M1/L1.
        return quantize_to_currency(self.quantity * self.unit_price, self.currency)

    @property
    def unit_price_display(self) -> Decimal:
        # unit_price is stored at Numeric(14,3) (widened for FINDINGS.md
        # L1 so a 3dp-currency invoice can hold a real 3-decimal price),
        # but a 2dp/0dp currency's unit_price should still DISPLAY at its
        # own real precision (e.g. "10.00" for USD, not "10.000") rather
        # than the column's full storage scale -- every export format
        # (PDF, email, .txt, for-robots.json) reads this, not raw
        # unit_price, so they all show the same figure.
        return quantize_to_currency(self.unit_price, self.currency)


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

    @property
    def amount_total_display(self) -> Decimal:
        # amount_total is stored in a Numeric(14,3) column, so ANY value
        # read back from the DB carries a 3-decimal-place scale
        # regardless of what quantum recompute_amount_total actually used
        # to compute it (Postgres normalizes to the column's declared
        # scale on write) -- e.g. a JPY amount_total correctly computed as
        # Decimal("1000") still round-trips as Decimal("1000.000"). Every
        # export format must re-quantize to the currency's real precision
        # at display time rather than trusting the raw column's scale.
        # See FINDINGS.md L1.
        return quantize_to_currency(self.amount_total, self.currency)


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
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
                .order_by(InvoiceLineItem.created_at)
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
                currency=invoice.currency,
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
    db: AsyncSession,
    invoice_id: UUID,
    cfg: AppConfig,
    export_data: InvoiceExportData | None = None,
) -> Result[bytes, InvoiceError]:
    """Renders a professional, printable PDF for the given invoice (see
    domain/invoices/pdf/ for the LaTeX class/template/renderer this calls
    into). Shared by both the customer-facing and admin PDF download
    routes AND the invoice-sent email's PDF attachment -- ownership/role
    checks belong at each caller (this function doesn't take a requesting
    user at all), this only knows how to build the PDF once an
    invoice_id has already been authorized.

    `export_data` lets a caller that already loaded the invoice's export
    data (e.g. notify.notify_invoice_sent, which builds the email body/
    .txt/.json from one snapshot) pass it straight through instead of
    this function re-querying independently -- avoids both the doubled
    query and the narrow TOCTOU where the PDF could reflect a different
    snapshot than the other attached formats in the same email (see
    FINDINGS.md L1). Route callers that only want the PDF still omit it
    and get the load-then-render path.
    """
    data = export_data
    if data is None:
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
            (li.description, li.quantity, li.unit_price, li.line_total, li.unit)
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
        "amount_total": str(data.amount_total_display),
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
                "unit_price": str(li.unit_price_display),
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
    # 73, not a round number -- matches the exact width of the header row
    # above (40 + 1 + 6 + 1 + 12 + 1 + 12), so the divider spans the full
    # table rather than falling one column short of "Line total"'s edge.
    lines.append("-" * 73)
    for li in data.line_items:
        # Unit appended to the description column (not the unit-price
        # column) to match templates._line_items_text/_line_items_table --
        # every rendering of a given invoice should place `unit` in the
        # same spot. See FINDINGS.md L2.
        unit_suffix = f" ({li.unit})" if li.unit else ""
        lines.append(
            f"{li.description + unit_suffix:<40} {str(li.quantity):>6} "
            f"{str(li.unit_price_display):>12} {str(li.line_total):>12}"
        )
    lines.append("-" * 73)
    # <60 (not <59) so the amount field starts one column later, landing
    # its right edge on the same column as "Line total" above -- <59 put
    # it one column short of that edge.
    lines.append(
        f"{'Total':<60} {str(data.amount_total_display):>12} {data.currency.upper()}"
    )
    lines.append("")
    if data.pay_url:
        lines.append(f"Pay online: {data.pay_url}")
    lines.append(f"Questions: {cfg.invoice_contact_email}")
    return "\n".join(lines) + "\n"
