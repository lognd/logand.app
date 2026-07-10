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
from logand_backend.domain.invoices.tax import categorizer, classification_store
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
    # Updated for the M2/M3 contract: only CONFIRMED/OVERRIDDEN classifications
    # auto-charge, so both items are pre-classified by a human (override) --
    # the old version relied on a `pending` Claude result charging immediately,
    # which no longer happens (it would flag review and charge nothing).
    await _seed_rule(db_session, "US-TN", "sales", "tangible-goods", "0.07")
    await _seed_rule(
        db_session, "US-customs", "import_duty", "imported-component", "0.02"
    )

    admin = await make_user(role="admin")
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

    await classification_store.override(
        db_session,
        classification_store.normalize_key("Widget"),
        category="tangible-goods",
        taxable=True,
        hts_code=None,
        admin_id=admin.id,
    )
    await classification_store.override(
        db_session,
        classification_store.normalize_key("PCB (imported)"),
        category="imported-component",
        taxable=True,
        hts_code=None,
        admin_id=admin.id,
    )

    async def boom(*_a, **_k):  # confirmed items must not hit Claude
        raise AssertionError("Claude was called for an overridden item")

    monkeypatch.setattr(categorizer, "_call_claude", boom)
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
    # Widget: FL customer has no sales rule -> falls back to origin TN 7% =
    # 7.00. PCB: customs import_duty 2% = 1.00. Total tax 8.00. Both items are
    # human-confirmed, so nothing is flagged for review.
    assert invoice.tax_amount == Decimal("8.00")
    assert invoice.amount_total == Decimal("158.00")
    assert invoice.needs_review is False


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
    # Updated for the M2/M3 contract: the auto `sales` charge only lands
    # because the item is human-confirmed (override); the hand-entered `use`
    # charge must still survive untouched regardless.
    await _seed_rule(db_session, "US-TN", "sales", "*", "0.07")
    admin = await make_user(role="admin")
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

    await classification_store.override(
        db_session,
        classification_store.normalize_key("Consulting"),
        category="*",
        taxable=True,
        hts_code=None,
        admin_id=admin.id,
    )

    async def boom(*_a, **_k):  # confirmed item must not hit Claude
        raise AssertionError("Claude was called for an overridden item")

    monkeypatch.setattr(categorizer, "_call_claude", boom)
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


async def _invoice_one_line(db, make_user, description, unit_price, address_state=None):
    customer = await make_user(role="customer")
    if address_state is not None:
        customer.address_state = address_state
    await db.commit()
    result = await create_invoice(
        db,
        customer.id,
        [LineItemInput(description=description, unit_price=Decimal(unit_price))],
        tax_origin_state="TN",
    )
    assert result.is_ok
    return result.danger_ok


async def _charges_for_invoice(db, invoice_id):
    return list(
        (
            await db.execute(
                select(InvoiceLineItemTax)
                .join(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
            )
        )
        .scalars()
        .all()
    )


async def test_pending_classification_is_not_charged_and_flags_review(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M2: a model-classified but NOT human-confirmed (pending) line must charge
    # nothing and gate the invoice behind review, not auto-charge money.
    await _seed_rule(db_session, "US-TN", "sales", "*", "0.07")
    invoice_id = await _invoice_one_line(db_session, make_user, "Gizmo", "100.00")

    async def fake_call(_cfg, _lines, _known, _kb):
        return {
            "decisions": [
                {"line_index": 0, "category": "*", "taxable": True, "rationale": "x"}
            ]
        }

    monkeypatch.setattr(categorizer, "_call_claude", fake_call)
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    await apply_auto_tax(db_session, cfg, invoice_id)

    assert await _charges_for_invoice(db_session, invoice_id) == []
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.tax_amount == Decimal(0)
    assert invoice.amount_total == Decimal("100.00")
    assert invoice.needs_review is True
    assert invoice.needs_review_reason == "1 line item(s) need tax review"


async def test_categorizer_failure_is_not_charged_and_flags_review(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M3: a categorizer OUTAGE (Claude errors while a key is configured) must
    # fail CLOSED-with-a-signal -- zero charge AND a visible review flag --
    # never silently under-collect with no signal.
    await _seed_rule(db_session, "US-TN", "sales", "*", "0.07")
    invoice_id = await _invoice_one_line(db_session, make_user, "Doohickey", "100.00")

    async def boom(*_a, **_k):
        raise RuntimeError("Claude is down")

    monkeypatch.setattr(categorizer, "_call_claude", boom)
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    await apply_auto_tax(db_session, cfg, invoice_id)

    assert await _charges_for_invoice(db_session, invoice_id) == []
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.tax_amount == Decimal(0)
    assert invoice.needs_review is True
    assert invoice.needs_review_reason == "1 line item(s) need tax review"


async def test_confirmed_taxable_line_is_charged_without_flag(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M2/M3: a human-confirmed taxable line charges normally and raises NO
    # review flag.
    await _seed_rule(db_session, "US-TN", "sales", "*", "0.07")
    admin = await make_user(role="admin")
    invoice_id = await _invoice_one_line(
        db_session, make_user, "Confirmed thing", "100.00"
    )

    await classification_store.override(
        db_session,
        classification_store.normalize_key("Confirmed thing"),
        category="*",
        taxable=True,
        hts_code=None,
        admin_id=admin.id,
    )

    async def boom(*_a, **_k):
        raise AssertionError("Claude was called for an overridden item")

    monkeypatch.setattr(categorizer, "_call_claude", boom)
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    await apply_auto_tax(db_session, cfg, invoice_id)

    charges = await _charges_for_invoice(db_session, invoice_id)
    assert [(c.tax_type, c.jurisdiction, c.rate) for c in charges] == [
        ("sales", "US-TN", Decimal("0.07"))
    ]
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.tax_amount == Decimal("7.00")
    assert invoice.needs_review is False


async def test_confirmed_tax_free_line_is_not_charged_and_not_flagged(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A genuinely tax-free CONFIRMED line (taxable=False, confirmed) charges
    # nothing AND raises no flag -- only unresolved/unconfirmed lines flag.
    await _seed_rule(db_session, "US-TN", "sales", "*", "0.07")
    admin = await make_user(role="admin")
    invoice_id = await _invoice_one_line(
        db_session, make_user, "Exempt service", "100.00"
    )

    await classification_store.override(
        db_session,
        classification_store.normalize_key("Exempt service"),
        category="service",
        taxable=False,
        hts_code=None,
        admin_id=admin.id,
    )

    async def boom(*_a, **_k):
        raise AssertionError("Claude was called for an overridden item")

    monkeypatch.setattr(categorizer, "_call_claude", boom)
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    await apply_auto_tax(db_session, cfg, invoice_id)

    assert await _charges_for_invoice(db_session, invoice_id) == []
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.tax_amount == Decimal(0)
    assert invoice.needs_review is False


async def test_sales_tax_is_single_source_destination_preferred(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # H1: origin TN 7% AND destination FL 6% both configured on a $100 taxable
    # line -> exactly ONE sales charge (destination FL 6% = 6.00 -> 106.00),
    # never both summed to 13.00.
    await _seed_rule(db_session, "US-TN", "sales", "*", "0.07")
    await _seed_rule(db_session, "US-FL", "sales", "*", "0.06")
    admin = await make_user(role="admin")
    invoice_id = await _invoice_one_line(
        db_session, make_user, "Taxable widget", "100.00", address_state="FL"
    )

    await classification_store.override(
        db_session,
        classification_store.normalize_key("Taxable widget"),
        category="*",
        taxable=True,
        hts_code=None,
        admin_id=admin.id,
    )

    async def boom(*_a, **_k):
        raise AssertionError("Claude was called for an overridden item")

    monkeypatch.setattr(categorizer, "_call_claude", boom)
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    await apply_auto_tax(db_session, cfg, invoice_id)

    charges = await _charges_for_invoice(db_session, invoice_id)
    sales_charges = [c for c in charges if c.tax_type == "sales"]
    # Exactly one sales charge, sourced to the DESTINATION (FL 6%).
    assert len(sales_charges) == 1
    assert (sales_charges[0].jurisdiction, sales_charges[0].rate) == (
        "US-FL",
        Decimal("0.06"),
    )
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.tax_amount == Decimal("6.00")
    assert invoice.amount_total == Decimal("106.00")


async def test_sales_tax_falls_back_to_origin_when_no_destination_rule(
    db_session, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # H1: an FL customer with ONLY a TN rule configured -> no destination rule,
    # falls back to the origin TN 7%, and no phantom second state is charged.
    await _seed_rule(db_session, "US-TN", "sales", "*", "0.07")
    admin = await make_user(role="admin")
    invoice_id = await _invoice_one_line(
        db_session, make_user, "Out-of-state widget", "100.00", address_state="FL"
    )

    await classification_store.override(
        db_session,
        classification_store.normalize_key("Out-of-state widget"),
        category="*",
        taxable=True,
        hts_code=None,
        admin_id=admin.id,
    )

    async def boom(*_a, **_k):
        raise AssertionError("Claude was called for an overridden item")

    monkeypatch.setattr(categorizer, "_call_claude", boom)
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    await apply_auto_tax(db_session, cfg, invoice_id)

    charges = await _charges_for_invoice(db_session, invoice_id)
    sales_charges = [c for c in charges if c.tax_type == "sales"]
    assert len(sales_charges) == 1
    assert (sales_charges[0].jurisdiction, sales_charges[0].rate) == (
        "US-TN",
        Decimal("0.07"),
    )
    invoice = await db_session.get(Invoice, invoice_id)
    assert invoice.tax_amount == Decimal("7.00")
    assert invoice.amount_total == Decimal("107.00")
