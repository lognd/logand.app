from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from logand_backend.app.config import AppConfig
from logand_backend.db.models.tax import TaxRule
from logand_backend.domain.invoices.tax import categorizer, knowledge_base
from logand_backend.scripts.fetch_tax_rules import RuleInput, upsert_rules


async def _seed(db, jur, ttype, cat, rate):
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


async def test_lookup_rate_falls_back_to_catchall(db_session) -> None:
    await _seed(db_session, "US-TN", "sales", "*", "0.07")
    hit = await knowledge_base.lookup_rate(
        db_session, jurisdiction="US-TN", tax_type="sales", category="service"
    )
    assert hit is not None
    rate, rule = hit
    assert rate == Decimal("0.07")
    assert rule.category == "*"


async def test_lookup_rate_none_when_no_rule(db_session) -> None:
    assert (
        await knowledge_base.lookup_rate(
            db_session, jurisdiction="US-XX", tax_type="sales", category="*"
        )
        is None
    )


async def test_upsert_rules_is_idempotent_and_supersedes(db_session) -> None:
    rules = [
        RuleInput(
            jurisdiction="US-TN",
            tax_type="sales",
            rate=Decimal("0.07"),
            source="TN DOR 2026",
            citation_url="https://www.tn.gov/revenue.html",
        )
    ]
    inserted, superseded = await upsert_rules(db_session, rules)
    assert (inserted, superseded) == (1, 0)

    # Re-running with the same rate is a no-op.
    inserted, superseded = await upsert_rules(db_session, rules)
    assert (inserted, superseded) == (0, 0)

    # A changed rate closes out the old rule and inserts a new current one.
    inserted, superseded = await upsert_rules(
        db_session,
        [
            RuleInput(
                jurisdiction="US-TN",
                tax_type="sales",
                rate=Decimal("0.08"),
                source="TN DOR 2026",
                citation_url="https://www.tn.gov/revenue.html",
            )
        ],
    )
    assert (inserted, superseded) == (1, 1)
    hit = await knowledge_base.lookup_rate(
        db_session, jurisdiction="US-TN", tax_type="sales", category="*"
    )
    assert hit is not None and hit[0] == Decimal("0.08")


async def test_categorize_and_price_end_to_end(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed the knowledge base: TN sales tax on goods, a customs duty on
    # imported components.
    await _seed(db_session, "US-TN", "sales", "tangible-goods", "0.07")
    await _seed(db_session, "US-customs", "import_duty", "imported-component", "0.02")

    cfg = AppConfig(anthropic_api_key="sk-test-fake")

    # Mock the Claude call: line 0 is a taxable good, line 1 an imported part.
    async def fake_call(_cfg, _lines, _known, _kb):
        return {
            "decisions": [
                {
                    "line_index": 0,
                    "category": "tangible-goods",
                    "taxable": True,
                    "rationale": "a physical product",
                },
                {
                    "line_index": 1,
                    "category": "imported-component",
                    "taxable": True,
                    "rationale": "an imported PCB",
                },
            ]
        }

    monkeypatch.setattr(categorizer, "_call_claude", fake_call)

    lines = [
        categorizer.LineInput(index=0, description="Widget"),
        categorizer.LineInput(index=1, description="PCB (imported)"),
    ]
    pricing = await categorizer.categorize_and_price(
        db_session,
        cfg,
        lines=lines,
        origin_jurisdiction="US-TN",
        destination_jurisdiction="US-customs",
    )

    by_index = {p.line_index: p for p in pricing}
    # Widget: taxed by TN sales at 7%, nothing from customs (no rule for its
    # category there).
    assert [(c.tax_type, c.jurisdiction, c.rate) for c in by_index[0].charges] == [
        ("sales", "US-TN", Decimal("0.07"))
    ]
    # PCB: customs import duty 2% (no TN rule for imported-component).
    assert [(c.tax_type, c.jurisdiction, c.rate) for c in by_index[1].charges] == [
        ("import_duty", "US-customs", Decimal("0.02"))
    ]
    # A fresh Claude classification is flagged pending (awaiting confirmation),
    # and the decision (with the model's rationale) is persisted per item.
    assert by_index[0].pending is True
    from logand_backend.domain.invoices.tax import classification_store

    row = await classification_store.get(
        db_session, classification_store.normalize_key("Widget")
    )
    assert row is not None and row.rationale == "a physical product"


async def test_categorize_and_price_caches_the_call(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(db_session, "US-TN", "sales", "*", "0.07")
    cfg = AppConfig(anthropic_api_key="sk-test-fake")

    calls = {"n": 0}

    async def fake_call(_cfg, _lines, _known, _kb):
        calls["n"] += 1
        return {
            "decisions": [
                {"line_index": 0, "category": "*", "taxable": True, "rationale": ""}
            ]
        }

    monkeypatch.setattr(categorizer, "_call_claude", fake_call)
    lines = [categorizer.LineInput(index=0, description="Thing")]

    for _ in range(2):
        await categorizer.categorize_and_price(
            db_session,
            cfg,
            lines=lines,
            origin_jurisdiction="US-TN",
            destination_jurisdiction=None,
        )
    # Second run is served from the TTL cache -- Claude is called once.
    assert calls["n"] == 1


async def test_categorize_and_price_noop_without_key(db_session) -> None:
    cfg = AppConfig()  # no anthropic_api_key
    out = await categorizer.categorize_and_price(
        db_session,
        cfg,
        lines=[categorizer.LineInput(index=0, description="Thing")],
        origin_jurisdiction="US-TN",
        destination_jurisdiction=None,
    )
    assert out == []


async def test_build_tax_report_aggregates_by_jurisdiction_and_category(
    db_session, make_user
) -> None:
    from datetime import datetime, timedelta, timezone

    from logand_backend.domain.invoices.service import (
        LineItemInput,
        LineItemTaxInput,
        create_invoice,
        send_invoice,
    )
    from logand_backend.domain.invoices.tax.report import build_tax_report

    customer = await make_user(role="customer")
    line_items = [
        LineItemInput(
            description="Widget",
            quantity=Decimal(1),
            unit_price=Decimal("100.00"),
            tax_category="tangible-goods",
            taxes=[
                LineItemTaxInput(
                    tax_type="sales", jurisdiction="US-TN", rate=Decimal("0.07")
                )
            ],
        ),
    ]
    inv_id = (
        await create_invoice(db_session, customer.id, line_items, tax_origin_state="TN")
    ).danger_ok
    await send_invoice(db_session, inv_id)  # 'sent' counts as reportable
    await db_session.flush()

    now = datetime.now(timezone.utc)
    report = await build_tax_report(
        db_session, from_date=now - timedelta(days=1), to_date=now + timedelta(days=1)
    )
    assert report.total_sales == Decimal("100.00")
    assert report.total_tax_collected == Decimal("7.00")
    assert report.filing_jurisdictions == ["US-TN"]
    row = report.by_jurisdiction[0]
    assert (row.jurisdiction, row.tax_type, row.tax_collected) == (
        "US-TN",
        "sales",
        Decimal("7.00"),
    )
    assert report.by_category[0].category == "tangible-goods"


async def test_confirmed_item_is_not_reclassified(
    db_session, make_user, monkeypatch
) -> None:
    from logand_backend.domain.invoices.tax import classification_store

    await _seed(db_session, "US-TN", "sales", "*", "0.07")
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    admin = await make_user(role="admin")

    calls = {"n": 0}

    async def fake_call(_cfg, _lines, _known, _kb):
        calls["n"] += 1
        return {
            "decisions": [
                {"line_index": 0, "category": "*", "taxable": True, "rationale": ""}
            ]
        }

    monkeypatch.setattr(categorizer, "_call_claude", fake_call)
    lines = [categorizer.LineInput(index=0, description="Bespoke thing")]

    # First pass classifies (pending) and prices.
    out = await categorizer.categorize_and_price(
        db_session,
        cfg,
        lines=lines,
        origin_jurisdiction="US-TN",
        destination_jurisdiction=None,
    )
    assert out[0].pending is True
    key = classification_store.normalize_key("Bespoke thing")
    await classification_store.confirm(db_session, key, admin.id)

    # Second pass: confirmed -> no Claude call, no longer pending.
    out2 = await categorizer.categorize_and_price(
        db_session,
        cfg,
        lines=lines,
        origin_jurisdiction="US-TN",
        destination_jurisdiction=None,
    )
    assert calls["n"] == 1
    assert out2[0].pending is False


async def test_override_outranks_claude(db_session, make_user, monkeypatch) -> None:
    from logand_backend.domain.invoices.tax import classification_store

    await _seed(db_session, "US-TN", "sales", "*", "0.07")
    cfg = AppConfig(anthropic_api_key="sk-test-fake")
    admin = await make_user(role="admin")

    # Admin pre-classifies the item as exempt.
    key = classification_store.normalize_key("Consulting")
    await classification_store.override(
        db_session,
        key,
        category="service",
        taxable=False,
        hts_code=None,
        admin_id=admin.id,
    )

    async def boom(*_a, **_k):  # Claude must not be called
        raise AssertionError("Claude was called for an overridden item")

    monkeypatch.setattr(categorizer, "_call_claude", boom)
    out = await categorizer.categorize_and_price(
        db_session,
        cfg,
        lines=[categorizer.LineInput(index=0, description="Consulting")],
        origin_jurisdiction="US-TN",
        destination_jurisdiction=None,
    )
    # Exempt -> no charges even though a TN sales rule exists.
    assert out[0].taxable is False
    assert out[0].charges == []


async def test_rate_limit_defers_new_item_without_failing(
    db_session, monkeypatch
) -> None:
    from logand_backend.domain.invoices.tax import classification_store

    await _seed(db_session, "US-TN", "sales", "*", "0.07")
    cfg = AppConfig(anthropic_api_key="sk-test-fake")

    async def rate_limited(*_a, **_k):
        raise categorizer.RateLimited()

    monkeypatch.setattr(categorizer, "_call_claude", rate_limited)
    out = await categorizer.categorize_and_price(
        db_session,
        cfg,
        lines=[categorizer.LineInput(index=0, description="New gizmo")],
        origin_jurisdiction="US-TN",
        destination_jurisdiction=None,
    )
    # Deferred: no charges, no crash, and nothing persisted (retried later).
    assert out == []
    assert (
        await classification_store.get(
            db_session, classification_store.normalize_key("New gizmo")
        )
        is None
    )
