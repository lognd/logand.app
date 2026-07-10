"""Auto-applies the do-as-we-go categorizer to a freshly created invoice
(docs/design/16-sales-tax.md Phase 6). Best-effort: never raises out of the
invoice creation path -- an unconfigured categorizer, no tax_rules, or a
failed Claude call all leave the invoice exactly as create_invoice built it.

Auto vs. manual charges: InvoiceLineItemTax.auto distinguishes a charge this
module wrote (auto=True) from one an admin entered by hand (auto=False, the
default -- see LineItemTaxInput/create_invoice). apply_auto_tax only ever
deletes+replaces a line's own auto=True rows, so re-running it (e.g. after a
customer's address is added later) can never clobber a hand-entered charge.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import (
    Invoice,
    InvoiceLineItem,
    InvoiceLineItemTax,
)
from logand_backend.db.models.users import User
from logand_backend.domain.invoices.service import (
    flag_invoice_needs_review,
    recompute_amount_total,
)
from logand_backend.domain.invoices.tax import categorizer
from logand_backend.logging import get_logger

_log = get_logger(__name__)

# Import duty applies at the US border regardless of which state the
# customer is in, so it's always offered to the categorizer/pricer
# alongside origin/destination -- see categorizer.categorize_and_price's
# extra_jurisdictions.
_CUSTOMS_JURISDICTION = "US-customs"


async def apply_auto_tax(db: AsyncSession, cfg: AppConfig, invoice_id: UUID) -> None:
    """Classifies and prices every line on `invoice_id` with the Claude
    categorizer, sourced from the seller's origin state x the customer's
    destination state (plus US-customs for import duty), and writes the
    result as auto=True InvoiceLineItemTax rows. No-op when the categorizer
    is unconfigured, the invoice/customer can't be found, or nothing comes
    back classified (e.g. no tax_rules yet) -- an invoice always still
    reflects whatever an admin entered by hand either way.
    """
    if not categorizer.is_configured(cfg):
        _log.info(
            "apply_auto_tax: categorizer not configured, skipping",
            extra={"invoice_id": str(invoice_id)},
        )
        return

    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        _log.warning(
            "apply_auto_tax: invoice not found", extra={"invoice_id": str(invoice_id)}
        )
        return

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
    if not line_items:
        return

    origin_state = invoice.tax_origin_state or cfg.invoice_tax_origin_state
    if not origin_state:
        _log.info(
            "apply_auto_tax: no origin state configured, skipping",
            extra={"invoice_id": str(invoice_id)},
        )
        return
    origin_jurisdiction = f"US-{origin_state}"

    customer = await db.get(User, invoice.customer_id)
    destination_jurisdiction = (
        f"US-{customer.address_state}" if customer and customer.address_state else None
    )

    lines = [
        categorizer.LineInput(index=i, description=li.description)
        for i, li in enumerate(line_items)
    ]
    pricing = await categorizer.categorize_and_price(
        db,
        cfg,
        lines=lines,
        origin_jurisdiction=origin_jurisdiction,
        destination_jurisdiction=destination_jurisdiction,
        extra_jurisdictions=[_CUSTOMS_JURISDICTION],
    )
    # NB: an EMPTY `pricing` is not a no-op here. When the categorizer is
    # configured but Claude fails/rate-limits, no line resolves and pricing is
    # empty -- every line is then unresolved and must gate the invoice behind
    # review (M3), not silently pass through with zero tax and no signal.
    pricing_by_index = {p.line_index: p for p in pricing}

    # Only a CONFIRMED/OVERRIDDEN classification auto-charges money. A pending
    # (model-only, not human-confirmed) classification -- or a line the
    # categorizer never resolved at all (rate-limit/error/unconfigured rule) --
    # must NOT be auto-charged and instead gates the invoice behind human
    # review. This makes the review workflow actually hold back money and makes
    # a categorizer outage fail CLOSED-with-a-signal instead of silently
    # under-collecting. See M2/M3 in docs/design/16-sales-tax.md.
    #
    # The charge mutations run in a SAVEPOINT (db.begin_nested) so a mid-loop
    # failure rolls back its own partial writes atomically -- the request's own
    # exception handler (api/invoices.py::create) may still commit the invoice,
    # and it must never persist half a line's charges against a stale
    # tax_amount/amount_total (L2).
    review_needed = 0
    async with db.begin_nested():
        for index, line_item in enumerate(line_items):
            p = pricing_by_index.get(index)
            confirmed = p is not None and not p.pending
            # Always clear this line's OWN auto rows first -- never a hand-
            # entered (auto=False) charge -- so a re-run (or a formerly-charged
            # line that is now pending/unresolved) never leaves a stale auto
            # charge behind. See module docstring.
            await db.execute(
                delete(InvoiceLineItemTax).where(
                    InvoiceLineItemTax.line_item_id == line_item.id,
                    InvoiceLineItemTax.auto.is_(True),
                )
            )
            if not confirmed:
                # Pending or unresolved -> charge nothing, flag for review.
                review_needed += 1
                continue
            line_item.taxable = p.taxable
            line_item.tax_category = p.category
            for charge in p.charges:
                db.add(
                    InvoiceLineItemTax(
                        line_item_id=line_item.id,
                        tax_type=charge.tax_type,
                        jurisdiction=charge.jurisdiction,
                        rate=charge.rate,
                        auto=True,
                    )
                )
        await db.flush()
        await recompute_amount_total(db, invoice_id)

    if review_needed:
        invoice = await db.get(Invoice, invoice_id)
        if invoice is not None:
            await flag_invoice_needs_review(
                db,
                invoice,
                f"{review_needed} line item(s) need tax review",
            )
    _log.info(
        "apply_auto_tax: applied categorizer to invoice",
        extra={
            "invoice_id": str(invoice_id),
            "lines_priced": len(pricing),
            "review_needed": review_needed,
        },
    )
