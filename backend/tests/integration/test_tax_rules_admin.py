from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from logand_backend.api.tax import TaxRuleCreateInput, create_tax_rule, list_tax_rules
from logand_backend.app.config import AppConfig
from logand_backend.auth.sessions import SessionInfo
from logand_backend.scripts.fetch_tax_rules import RuleInput, add_tax_rule


def _admin_session() -> SessionInfo:
    return SessionInfo(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="admin",
        csrf_secret="x",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


async def test_add_tax_rule_rejects_non_government_citation(db_session) -> None:
    cfg = AppConfig()
    rule = RuleInput(
        jurisdiction="US-TN",
        tax_type="sales",
        rate=Decimal("0.07"),
        source="Some blog",
        citation_url="https://example.com/tn-rate",
    )
    result = await add_tax_rule(db_session, cfg, rule)
    assert result.is_err
    assert "government source" in result.danger_err


async def test_add_tax_rule_accepts_gov_citation_and_persists(db_session) -> None:
    cfg = AppConfig()
    rule = RuleInput(
        jurisdiction="US-TN",
        tax_type="sales",
        rate=Decimal("0.07"),
        source="TN DOR 2026",
        citation_url="https://www.tn.gov/revenue.html",
    )
    result = await add_tax_rule(db_session, cfg, rule)
    assert not result.is_err
    row = result.danger_ok
    assert row.citation_url == "https://www.tn.gov/revenue.html"
    assert row.rate == Decimal("0.07")


async def test_add_tax_rule_accepts_allowlisted_domain(db_session) -> None:
    cfg = AppConfig(tax_citation_allowed_domains="floridarevenue.com")
    rule = RuleInput(
        jurisdiction="US-FL",
        tax_type="sales",
        rate=Decimal("0.06"),
        source="FL DOR 2026",
        citation_url="https://floridarevenue.com/taxes/rates",
    )
    result = await add_tax_rule(db_session, cfg, rule)
    assert not result.is_err


async def test_create_and_list_tax_rules_endpoint_functions(db_session) -> None:
    admin = _admin_session()

    reject_body = TaxRuleCreateInput(
        jurisdiction="US-TN",
        tax_type="sales",
        category="*",
        rate="0.07",
        source="Some blog",
        citation_url="https://example.com/tn-rate",
    )
    from fastapi import HTTPException

    try:
        await create_tax_rule(reject_body, admin, db_session)
        raise AssertionError("expected HTTPException for non-government citation")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "government source" in exc.detail

    accept_body = TaxRuleCreateInput(
        jurisdiction="US-TN",
        tax_type="sales",
        category="*",
        rate="0.07",
        source="TN DOR 2026",
        citation_url="https://www.tn.gov/revenue.html",
    )
    created = await create_tax_rule(accept_body, admin, db_session)
    assert created["jurisdiction"] == "US-TN"
    assert created["citation_url"] == "https://www.tn.gov/revenue.html"
    assert created["rate"] == "0.07"

    rows = await list_tax_rules(admin, db_session)
    assert any(r["id"] == created["id"] for r in rows)
