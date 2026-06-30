from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Result

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
    raise NotImplementedError("sum line items; needs db.models.invoices")


async def create_invoice(
    db: AsyncSession, customer_id: UUID, line_items: list[LineItemInput], memo: str | None = None
) -> Result[UUID, InvoiceError]:
    raise NotImplementedError("insert invoice + line items, then recompute_amount_total")


async def send_invoice(db: AsyncSession, invoice_id: UUID) -> Result[None, InvoiceError]:
    """draft -> sent. Once sent, line items are frozen (docs/design/04) --
    enforce that here, not just in the API layer, since domain functions
    are the only thing that should be trusted to hold this invariant."""
    raise NotImplementedError("transition status, freeze line items")


async def void_invoice(db: AsyncSession, invoice_id: UUID) -> Result[None, InvoiceError]:
    raise NotImplementedError("sent/overdue -> void, validate current status first")
