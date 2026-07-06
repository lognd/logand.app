from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.invoices import (
    Invoice,
    InvoiceLineItem,
    InvoiceLineItemTax,
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
    """Aggregate reportable invoices in [from_date, to_date). All money is
    quantized to the currency's real precision with the same rule the invoices
    use, so the report reconciles exactly with what customers were charged."""
    invoices = (
        (
            await db.execute(
                select(Invoice).where(
                    Invoice.created_at >= from_date,
                    Invoice.created_at < to_date,
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
