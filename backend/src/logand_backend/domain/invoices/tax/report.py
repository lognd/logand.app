from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import (
    Invoice,
    InvoiceLineItem,
    InvoiceLineItemTax,
    Refund,
)
from logand_backend.domain.payments.currency import quantize_to_currency

# The admin tax-filing view (docs/design/16-sales-tax.md). Aggregates, over a
# date range, everything needed to file: how much was sold of each tax
# category, how much tax was collected per jurisdiction + tax type, and which
# jurisdictions therefore have a filing obligation. Deterministic -- built
# from the stored line items and charge rows, the same figures the invoices
# show; safe to hand straight to an accountant (or to Claude) for form-filling.

# Statuses that count as issued for tax purposes -- a draft/void invoice is
# not a sale.
_REPORTABLE_STATUSES = ("sent", "overdue", "paid")


@dataclass(frozen=True)
class JurisdictionTaxRow:
    jurisdiction: str
    tax_type: str
    taxable_base: Decimal
    tax_collected: Decimal


@dataclass(frozen=True)
class CategorySalesRow:
    category: str
    gross: Decimal
    taxable_gross: Decimal


@dataclass(frozen=True)
class TaxReport:
    from_date: datetime
    to_date: datetime
    currency: str
    invoice_count: int
    total_sales: Decimal
    # NET of succeeded refunds (allocated to tax proportionally per invoice --
    # see build_tax_report, L1). The per-jurisdiction rows below stay GROSS.
    total_tax_collected: Decimal
    by_jurisdiction: list[JurisdictionTaxRow]
    by_category: list[CategorySalesRow]
    # Distinct jurisdictions with collected tax -> the ones you must file for.
    filing_jurisdictions: list[str]


async def build_tax_report(
    db: AsyncSession,
    *,
    from_date: datetime,
    to_date: datetime,
    currency: str = "usd",
) -> TaxReport:
    """Aggregate reportable invoices over the INCLUSIVE calendar range
    [from_date, to_date] -- `to_date` is the last day to include and its WHOLE
    day counts (an invoice created at 14:00 on the to_date is in the report),
    so filing "Jan 1 to Jan 31" no longer drops everything on Jan 31 (M1).
    `to_date` is expected to be that day's midnight (as the API passes it); the
    filter runs to the following midnight, exclusive.

    All money is quantized to the currency's real precision with the same rule
    the invoices use, so the report reconciles exactly with what customers were
    charged. `total_tax_collected` is net of succeeded refunds, allocated
    proportionally (see below); the per-jurisdiction rows stay GROSS because
    the refund tables carry no per-jurisdiction/per-tax breakdown to allocate
    against (L1)."""
    to_date_exclusive = to_date + timedelta(days=1)
    invoices = (
        (
            await db.execute(
                select(Invoice).where(
                    Invoice.created_at >= from_date,
                    Invoice.created_at < to_date_exclusive,
                    Invoice.status.in_(_REPORTABLE_STATUSES),
                    Invoice.deleted_at.is_(None),
                    Invoice.currency == currency,
                )
            )
        )
        .scalars()
        .all()
    )
    invoice_ids = [inv.id for inv in invoices]

    # Batch: all line items and all their tax charges for these invoices in
    # two queries, then aggregate in memory.
    line_items = []
    charges_by_line: dict = {}
    if invoice_ids:
        line_items = (
            (
                await db.execute(
                    select(InvoiceLineItem).where(
                        InvoiceLineItem.invoice_id.in_(invoice_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        line_ids = [li.id for li in line_items]
        if line_ids:
            for charge in (
                (
                    await db.execute(
                        select(InvoiceLineItemTax).where(
                            InvoiceLineItemTax.line_item_id.in_(line_ids)
                        )
                    )
                )
                .scalars()
                .all()
            ):
                charges_by_line.setdefault(charge.line_item_id, []).append(charge)

    total_sales = Decimal(0)
    total_tax = Decimal(0)
    jur: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
    cat: dict[str, tuple[Decimal, Decimal]] = {}

    for li in line_items:
        line_total = quantize_to_currency(li.quantity * li.unit_price, currency)
        total_sales += line_total
        category = li.tax_category or "*"
        c_gross, c_taxable = cat.get(category, (Decimal(0), Decimal(0)))
        cat[category] = (
            c_gross + line_total,
            c_taxable + (line_total if li.taxable else Decimal(0)),
        )
        if not li.taxable:
            continue
        for charge in charges_by_line.get(li.id, []):
            amount = quantize_to_currency(line_total * charge.rate, currency)
            total_tax += amount
            key = (charge.jurisdiction or "(none)", charge.tax_type)
            base, collected = jur.get(key, (Decimal(0), Decimal(0)))
            jur[key] = (base + line_total, collected + amount)

    # L1: a partial refund leaves its payment/invoice "paid", so its tax keeps
    # counting unless we net it out. Refund rows carry no per-tax breakdown, so
    # allocate each invoice's succeeded refunds to tax PROPORTIONALLY by that
    # invoice's own tax share (tax_amount / amount_total) and subtract from the
    # top-line total. Per-jurisdiction rows are left gross (documented on the
    # dataclass) since there is nothing to allocate a refund to at that grain.
    if invoice_ids:
        refunded_by_invoice: dict = {}
        for r_invoice_id, r_amount in (
            (
                await db.execute(
                    select(Refund.invoice_id, Refund.amount).where(
                        Refund.invoice_id.in_(invoice_ids),
                        Refund.status == "succeeded",
                    )
                )
            )
            .tuples()
            .all()
        ):
            refunded_by_invoice[r_invoice_id] = (
                refunded_by_invoice.get(r_invoice_id, Decimal(0)) + r_amount
            )
        for inv in invoices:
            refunded = refunded_by_invoice.get(inv.id)
            if not refunded or inv.amount_total <= 0:
                continue
            tax_fraction = inv.tax_amount / inv.amount_total
            refunded_tax = quantize_to_currency(refunded * tax_fraction, currency)
            total_tax -= refunded_tax
        if total_tax < 0:
            total_tax = Decimal(0)

    by_jurisdiction = sorted(
        (
            JurisdictionTaxRow(
                jurisdiction=j, tax_type=t, taxable_base=base, tax_collected=collected
            )
            for (j, t), (base, collected) in jur.items()
        ),
        key=lambda r: (r.jurisdiction, r.tax_type),
    )
    by_category = sorted(
        (
            CategorySalesRow(category=c, gross=g, taxable_gross=tg)
            for c, (g, tg) in cat.items()
        ),
        key=lambda r: r.category,
    )
    filing = sorted({r.jurisdiction for r in by_jurisdiction if r.tax_collected > 0})

    return TaxReport(
        from_date=from_date,
        to_date=to_date,
        currency=currency,
        invoice_count=len(invoices),
        total_sales=total_sales,
        total_tax_collected=total_tax,
        by_jurisdiction=by_jurisdiction,
        by_category=by_category,
        filing_jurisdictions=filing,
    )
