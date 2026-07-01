from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel
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


class LineItemInput(BaseModel):
    model_config = {}

    description: str
    quantity: Decimal = Decimal(1)
    unit_price: Decimal


async def recompute_amount_total(db: AsyncSession, invoice_id: UUID) -> Decimal:
    """Sums invoice_line_items for invoice_id and writes it back to
    invoices.amount_total in the same transaction. Called on every write
    path -- amount_total must never be trusted from client input
    (docs/design/04, the tamper vector this exists to close)."""
    line_items = (
        await db.execute(
            select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
        )
    ).scalars()
    total = sum((li.quantity * li.unit_price for li in line_items), Decimal(0))

    invoice = await db.get(Invoice, invoice_id)
    if invoice is not None:
        invoice.amount_total = total
        await db.flush()
    return total


async def create_invoice(
    db: AsyncSession,
    customer_id: UUID,
    line_items: list[LineItemInput],
    memo: str | None = None,
) -> Result[UUID, InvoiceError]:
    invoice_id = uuid4()
    invoice = Invoice(id=invoice_id, customer_id=customer_id, memo=memo, status="draft")
    db.add(invoice)
    for item in line_items:
        db.add(
            InvoiceLineItem(
                id=uuid4(),
                invoice_id=invoice_id,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
        )
    await db.flush()
    await recompute_amount_total(db, invoice_id)
    return Ok(invoice_id)


async def send_invoice(
    db: AsyncSession, invoice_id: UUID
) -> Result[None, InvoiceError]:
    """draft -> sent. Once sent, line items are frozen (docs/design/04) --
    enforce that here, not just in the API layer, since domain functions
    are the only thing that should be trusted to hold this invariant."""
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        return Err(InvoiceError.NotFound)
    if invoice.status != "draft":
        return Err(InvoiceError.InvalidState)
    # NOTE: "freezing" line items is enforced by never exposing a line-item
    # mutation path for non-draft invoices in api/invoices.py -- there is no
    # separate frozen flag on InvoiceLineItem to maintain here.
    invoice.status = "sent"
    await db.flush()
    return Ok(None)


async def void_invoice(
    db: AsyncSession, invoice_id: UUID
) -> Result[None, InvoiceError]:
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        return Err(InvoiceError.NotFound)
    if invoice.status not in ("sent", "overdue"):
        return Err(InvoiceError.InvalidState)
    invoice.status = "void"
    await db.flush()
    return Ok(None)


async def generate_invoice_pdf(
    db: AsyncSession, invoice_id: UUID, cfg: AppConfig
) -> Result[bytes, InvoiceError]:
    """Renders a professional, printable PDF for the given invoice (see
    domain/invoices/pdf/ for the LaTeX class/template/renderer this calls
    into). Shared by both the customer-facing and admin PDF download
    routes -- ownership/role checks belong in the API layer (this function
    doesn't take a requesting user at all), this only knows how to build
    the PDF once an invoice_id has already been authorized.
    """
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or invoice.deleted_at is not None:
        return Err(InvoiceError.NotFound)

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

    data = build_invoice_pdf_data(
        invoice_id=str(invoice.id),
        status=invoice.status,
        currency=invoice.currency,
        amount_total=invoice.amount_total,
        due_date=invoice.due_date.isoformat() if invoice.due_date else None,
        created_at=invoice.created_at.date().isoformat(),
        memo=invoice.memo,
        customer_email=customer_email,
        line_items=[(li.description, li.quantity, li.unit_price) for li in line_items],
        business_name=cfg.invoice_business_name,
        business_details=cfg.invoice_business_details,
        contact_email=cfg.invoice_contact_email,
        # Only a real, actionable link for an invoice a customer can
        # actually pay yet (docs/design/04: draft/void invoices aren't
        # payable) -- a "Pay online" link on a draft/void PDF would be
        # misleading, since hitting that endpoint in that state 409s.
        pay_url=(
            f"{cfg.public_base_url}/invoices/{invoice.id}/pay"
            if invoice.status in ("sent", "overdue")
            else None
        ),
    )
    # render_invoice_pdf shells out to latexmk -- real (if brief) CPU/IO
    # work that would otherwise block the event loop for every other
    # concurrent request while one PDF compiles.
    pdf_bytes = await asyncio.to_thread(render_invoice_pdf, data)
    return Ok(pdf_bytes)
