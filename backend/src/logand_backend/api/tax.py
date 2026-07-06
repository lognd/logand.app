from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.tax import ItemTaxClassification, TaxRule
from logand_backend.domain.invoices.tax import classification_store
from logand_backend.domain.invoices.tax.stripe_reconcile import reconcile_stripe_tax
from logand_backend.logging import get_logger
from logand_backend.scripts.fetch_tax_rules import RuleInput, add_tax_rule

_log = get_logger(__name__)

# Admin review surface for the do-as-we-go item tax classifications
# (docs/design/16-sales-tax.md Phase 5). Claude-produced classifications land
# as `pending`; an admin confirms them as-is or overrides them. A human
# decision is authoritative and never re-asked.
router = APIRouter(prefix="/api/admin/tax", tags=["admin", "tax"])


def _serialize(row: ItemTaxClassification) -> dict:
    return {
        "id": str(row.id),
        "normalized_key": row.normalized_key,
        "description": row.description,
        "category": row.category,
        "taxable": row.taxable,
        "hts_code": row.hts_code,
        "status": row.status,
        "source": row.source,
        "model": row.model,
        "rationale": row.rationale,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/classifications")
async def list_classifications(
    status: str | None = None,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List item classifications; pass status=pending to see what needs a
    human decision."""
    rows = await classification_store.list_by_status(db, status)
    return [_serialize(r) for r in rows]


class OverrideInput(BaseModel):
    category: str
    taxable: bool
    hts_code: str | None = None


@router.post("/classifications/{key}/confirm")
async def confirm_classification(
    key: str,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept the current (pending) classification as-is."""
    row = await classification_store.confirm(db, key, admin.user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="classification not found")
    return _serialize(row)


@router.post("/classifications/{key}/override")
async def override_classification(
    key: str,
    body: OverrideInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Replace the classification with an explicit human choice (creates it if
    the item hasn't been seen yet)."""
    row = await classification_store.override(
        db,
        key,
        category=body.category,
        taxable=body.taxable,
        hts_code=body.hts_code,
        admin_id=admin.user_id,
    )
    return _serialize(row)


@router.get("/stripe-reconcile")
async def stripe_reconcile(
    from_date: date,
    to_date: date,
    _admin: SessionInfo = Depends(require_admin),
) -> dict:
    """Stripe's own tax-collected totals for [from_date, to_date], for an
    admin to eyeball against build_tax_report's deterministic figures for
    the same period. Best-effort -- see
    domain/invoices/tax/stripe_reconcile.py: an unconfigured Stripe account
    or any failure in the round trip to Stripe returns zeros, never a 5xx.
    """
    cfg = AppConfig.from_external(argparse.Namespace())
    summary = await reconcile_stripe_tax(cfg, from_date, to_date)
    return {
        "total_tax_collected": str(summary.total_tax_collected),
        "by_jurisdiction": {k: str(v) for k, v in summary.by_jurisdiction.items()},
        "transaction_count": summary.transaction_count,
    }


def _serialize_rule(row: TaxRule) -> dict:
    return {
        "id": str(row.id),
        "jurisdiction": row.jurisdiction,
        "tax_type": row.tax_type,
        "category": row.category,
        "rate": str(row.rate),
        "source": row.source,
        "citation_url": row.citation_url,
        "effective_from": row.effective_from.isoformat(),
    }


@router.get("/rules")
async def list_tax_rules(
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Lists the current (effective_to IS NULL) tax_rules knowledge-base
    rows, for the admin rates page (docs/design/16-sales-tax.md)."""
    rows = (
        (
            await db.execute(
                select(TaxRule)
                .where(TaxRule.effective_to.is_(None))
                .order_by(TaxRule.jurisdiction, TaxRule.tax_type, TaxRule.category)
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_rule(r) for r in rows]


class TaxRuleCreateInput(BaseModel):
    """Admin-entered rate. Rate accepted as a decimal string or number
    (e.g. "0.07"); citation_url must be a government source -- see
    domain/invoices/tax/citation.py. Claude never sets rates; an admin
    always enters and cites them."""

    jurisdiction: str = Field(min_length=1)
    tax_type: str = Field(min_length=1)
    category: str = "*"
    rate: str
    source: str = Field(min_length=1)
    citation_url: str = Field(min_length=1)


@router.post("/rules")
async def create_tax_rule(
    body: TaxRuleCreateInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Adds an admin-entered rate to the tax_rules knowledge base. Requires a
    government-source citation URL; rejects anything else with a 400."""
    try:
        rate = Decimal(body.rate)
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=400, detail="rate must be a decimal number"
        ) from exc
    try:
        rule = RuleInput(
            jurisdiction=body.jurisdiction,
            tax_type=body.tax_type,
            category=body.category,
            rate=rate,
            source=body.source,
            citation_url=body.citation_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cfg = AppConfig.from_external(argparse.Namespace())
    result = await add_tax_rule(db, cfg, rule)
    if result.is_err:
        _log.info(
            "create_tax_rule: rejected",
            extra={"admin_id": str(admin.user_id), "error": result.danger_err},
        )
        raise HTTPException(status_code=400, detail=result.danger_err)
    await db.commit()
    row = result.danger_ok
    _log.info(
        "create_tax_rule: added",
        extra={
            "admin_id": str(admin.user_id),
            "jurisdiction": row.jurisdiction,
            "tax_type": row.tax_type,
            "category": row.category,
        },
    )
    return _serialize_rule(row)
