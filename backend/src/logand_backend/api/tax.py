from __future__ import annotations

import argparse
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.tax import ItemTaxClassification
from logand_backend.domain.invoices.tax import classification_store
from logand_backend.domain.invoices.tax.stripe_reconcile import reconcile_stripe_tax

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
