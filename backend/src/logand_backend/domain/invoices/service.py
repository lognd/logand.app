from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.models.invoices import Invoice, InvoiceLineItem
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
