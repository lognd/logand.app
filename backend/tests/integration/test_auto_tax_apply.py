from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import (
    Invoice,
    InvoiceLineItem,
    InvoiceLineItemTax,
)
from logand_backend.db.models.tax import TaxRule
from logand_backend.domain.invoices.service import (
    LineItemInput,
    LineItemTaxInput,
    create_invoice,
)
from logand_backend.domain.invoices.tax import categorizer
from logand_backend.domain.invoices.tax.apply import apply_auto_tax


async def _seed_rule(db, jur, ttype, cat, rate):
    db.add(
        TaxRule(
            jurisdiction=jur,
            tax_type=ttype,
            category=cat,
            rate=Decimal(rate),
            effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    await db.flush()


async def test_apply_auto_tax_writes_charges_and_recomputes_total(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_rule(db_session, "US-TN", "sales", "tangible-goods", "0.07")
    await _seed_rule(
        db_session, "US-customs", "import_duty", "imported-component", "0.02"
    )

    customer = await make_user(role="customer")
    customer.address_state = "FL"
    await db_session.commit()

    result = await create_invoice(
        db_session,
        customer.id,
        [
            LineItemInput(description="Widget", unit_price=Decimal("100.00")),
            LineItemInput(description="PCB (imported)", unit_price=Decimal("50.00")),
        ],
        tax_origin_state="TN",
    )
    assert result.is_ok
    invoice_id = result.danger_ok

    async def fake_call(_cfg, lines, _known, _kb):
        return {
            "decisions": [
                {
                    "line_index": 0,
                    "category": "tangible-goods",
                    "taxable": True,
                    "rationale": "widget",
                },
                {
                    "line_index": 1,
                    "category": "imported-component",
                    "taxable": True,
                    "rationale": "pcb",
                },
            ]
        }

    monkeypatch.setattr(categorizer, "_call_claude", fake_call)
    cfg = AppConfig(anthropic_api_key="sk-test-fake")

    await apply_auto_tax(db_session, cfg, invoice_id)

    line_items = (
        (
            await db_session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
                .order_by(InvoiceLineItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert len(line_items) == 2

    widget_taxes = (
        (
            await db_session.execute(
                select(InvoiceLineItemTax).where(
                    InvoiceLineItemTax.line_item_id == line_items[0].id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(t.tax_type, t.jurisdiction, t.rate, t.auto) for t in widget_taxes] == [
        ("sales", "US-TN", Decimal("0.07"), True)
    ]

    pcb_taxes = (
        (
            await db_session.execute(
                select(InvoiceLineItemTax).where(
                    InvoiceLineItemTax.line_item_id == line_items[1].id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(t.tax_type, t.jurisdiction, t.rate, t.auto) for t in pcb_taxes] == [
        ("import_duty", "US-customs", Decimal("0.02"), True)
    ]

    invoice = await db_session.get(Invoice, invoice_id)
    # 100 * 0.07 (TN sales) + 50 * 0.02 (customs duty) = 7.00 + 1.00 = 8.00
    assert invoice.tax_amount == Decimal("8.00")
    assert invoice.amount_total == Decimal("158.00")


async def test_apply_auto_tax_is_a_noop_when_categorizer_unconfigured(
    db_session, make_user
) -> None:
    customer = await make_user(role="customer")
    result = await create_invoice(
        db_session,
        customer.id,
        [LineItemInput(description="Widget", unit_price=Decimal("100.00"))],
        tax_origin_state="TN",
    )
    assert result.is_ok
    invoice_id = result.danger_ok

    cfg = AppConfig(anthropic_api_key=None)
    await apply_auto_tax(db_session, cfg, invoice_id)

    charges = (
        (
            await db_session.execute(
                select(InvoiceLineItemTax)
                .join(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
            )
        )
        .scalars()
        .all()
    )
    assert charges == []

    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.amount_total == Decimal("100.00")
    assert invoice.tax_amount == Decimal(0)


async def test_apply_auto_tax_never_overwrites_a_hand_entered_charge(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_rule(db_session, "US-TN", "sales", "*", "0.07")
    customer = await make_user(role="customer")

    result = await create_invoice(
        db_session,
        customer.id,
        [
            LineItemInput(
                description="Consulting",
                unit_price=Decimal("100.00"),
                taxes=[
                    LineItemTaxInput(
                        tax_type="use", jurisdiction="US-TN", rate=Decimal("0.05")
                    )
                ],
            )
        ],
        tax_origin_state="TN",
    )
    assert result.is_ok
    invoice_id = result.danger_ok

    async def fake_call(_cfg, _lines, _known, _kb):
        return {
            "decisions": [
                {"line_index": 0, "category": "*", "taxable": True, "rationale": ""}
            ]
        }

    monkeypatch.setattr(categorizer, "_call_claude", fake_call)
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    await apply_auto_tax(db_session, cfg, invoice_id)

    line_item = (
        await db_session.execute(
            select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
        )
    ).scalar_one()
    charges = (
        (
            await db_session.execute(
                select(InvoiceLineItemTax).where(
                    InvoiceLineItemTax.line_item_id == line_item.id
                )
            )
        )
        .scalars()
        .all()
    )
    by_type = {(c.tax_type, c.auto): c for c in charges}
    # The hand-entered "use" charge survives untouched...
    assert ("use", False) in by_type
    # ...alongside the new auto "sales" charge apply_auto_tax added.
    assert ("sales", True) in by_type
