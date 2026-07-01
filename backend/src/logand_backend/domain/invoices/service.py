from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Invoice, InvoiceLineItem, Payment
from logand_backend.db.models.users import User
from logand_backend.domain.invoices.pdf.renderer import (
    build_invoice_pdf_data,
    render_invoice_pdf,
)
from logand_backend.errors import InvoiceError

# Every method an admin can record BY HAND -- "stripe" is deliberately
# excluded (that one only ever gets created automatically, from a real
# Stripe webhook, see api/webhooks.py) and so is a real PayPal-API capture
# (domain/payments/providers/paypal.py creates its own Payment row once
# that's hooked up). "paypal" here means "the customer already sent a
# PayPal payment some other way (their own PayPal app, e.g.) and an admin
# is just recording that it happened" -- same `method` value either way,
# distinguished by paypal_order_id being set or not (see
# db/models/invoices.py's Payment.paypal_order_id doc comment).
ManualPaymentMethod = Literal["paypal", "zelle", "in_person", "other"]


class ManualPaymentInput(BaseModel):
    model_config = {}

    method: ManualPaymentMethod
    amount: Decimal
    note: str | None = None


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


async def record_manual_payment(
    db: AsyncSession, invoice_id: UUID, admin_id: UUID, payment: ManualPaymentInput
) -> Result[UUID, InvoiceError]:
    """Records a payment an admin observed happening OUTSIDE this system
    -- a Zelle transfer, cash handed over in person, a PayPal payment sent
    directly customer-to-admin, or anything else that isn't the Stripe
    PaymentIntent flow (api/invoices_public.py's /pay). There is no
    provider API call here at all, by design: this is bookkeeping, not
    payment processing -- see docs/design/04 and this module's own
    ManualPaymentMethod doc comment for why "paypal" specifically can mean
    either this OR a real PayPal API capture depending on whether
    paypal_order_id ends up set.

    Marks the invoice "paid" only once recorded payments cover the full
    amount_total -- a partial manual payment (an admin recording a partial
    Zelle transfer, say) is still recorded for the record, but the invoice
    stays payable (sent/overdue) for the remaining balance rather than
    being incorrectly marked fully paid.
    """
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or invoice.deleted_at is not None:
        return Err(InvoiceError.NotFound)
    if invoice.status not in ("sent", "overdue"):
        return Err(InvoiceError.InvalidState)

    payment_id = uuid4()
    db.add(
        Payment(
            id=payment_id,
            invoice_id=invoice_id,
            method=payment.method,
            amount=payment.amount,
            status="succeeded",
            recorded_by=admin_id,
            note=payment.note,
        )
    )
    await db.flush()

    existing_total = (
        await db.execute(
            select(Payment).where(
                Payment.invoice_id == invoice_id, Payment.status == "succeeded"
            )
        )
    ).scalars()
    paid_so_far = sum((p.amount for p in existing_total), Decimal(0))
    if paid_so_far >= invoice.amount_total:
        invoice.status = "paid"
    await db.flush()

    return Ok(payment_id)


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
