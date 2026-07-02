from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api.errors import to_http_exception
from logand_backend.auth.sessions import SessionInfo, require_admin
from logand_backend.db.base import get_db
from logand_backend.db.models.bom import BillOfMaterials
from logand_backend.domain.bom.service import (
    BomCostBreakdown,
    add_material_line,
    compute_cost_breakdown,
    consume_bom,
    create_bom,
    delete_bom,
    get_bom,
    list_boms,
    remove_material_line,
)

router = APIRouter(prefix="/api/admin/boms", tags=["admin", "bom"])


class CreateBomInput(BaseModel):
    model_config = {}

    name: str
    labor_hours: Decimal = Decimal(0)
    labor_rate: Decimal = Decimal(0)
    overhead_percent: Decimal = Decimal(0)
    description: str | None = None


class AddMaterialLineInput(BaseModel):
    model_config = {}

    item_id: UUID
    quantity_per_unit: int


class ConsumeBomInput(BaseModel):
    model_config = {}

    build_quantity: int
    reason: str | None = None


def _bom_summary(bom: BillOfMaterials) -> dict:
    return {
        "id": str(bom.id),
        "name": bom.name,
        "description": bom.description,
        "labor_hours": str(bom.labor_hours),
        "labor_rate": str(bom.labor_rate),
        "overhead_percent": str(bom.overhead_percent),
    }


def _breakdown_summary(breakdown: BomCostBreakdown) -> dict:
    return {
        "material_lines": [
            {
                "item_id": str(line.item_id),
                "item_name": line.item_name,
                "quantity": line.quantity,
                "unit_cost": str(line.unit_cost),
                "line_cost": str(line.line_cost),
            }
            for line in breakdown.material_lines
        ],
        "material_cost": str(breakdown.material_cost),
        "labor_hours": str(breakdown.labor_hours),
        "labor_cost": str(breakdown.labor_cost),
        "overhead_percent": str(breakdown.overhead_percent),
        "overhead_cost": str(breakdown.overhead_cost),
        "total_cost": str(breakdown.total_cost),
    }


@router.post("")
async def create(
    body: CreateBomInput,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await create_bom(
        db,
        body.name,
        body.labor_hours,
        body.labor_rate,
        body.overhead_percent,
        body.description,
    )
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


@router.get("")
async def list_all(
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await list_boms(db)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return [_bom_summary(bom) for bom in result.danger_ok]


@router.get("/{bom_id}")
async def get_one(
    bom_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await get_bom(db, bom_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return _bom_summary(result.danger_ok)


@router.delete("/{bom_id}")
async def delete_one(
    bom_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await delete_bom(db, bom_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "deleted"}


@router.post("/{bom_id}/lines")
async def add_line(
    bom_id: UUID,
    body: AddMaterialLineInput,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await add_material_line(db, bom_id, body.item_id, body.quantity_per_unit)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"id": str(result.danger_ok)}


@router.delete("/{bom_id}/lines/{item_id}")
async def remove_line(
    bom_id: UUID,
    item_id: UUID,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await remove_material_line(db, bom_id, item_id)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"status": "removed"}


@router.get("/{bom_id}/cost")
async def get_cost_breakdown(
    bom_id: UUID,
    build_quantity: int = 1,
    _admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The real material/time/overhead price breakdown -- what task #77's
    invoice-import UI fetches to populate line items from."""
    result = await compute_cost_breakdown(db, bom_id, build_quantity)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return _breakdown_summary(result.danger_ok)


@router.post("/{bom_id}/consume")
async def consume(
    bom_id: UUID,
    body: ConsumeBomInput,
    admin: SessionInfo = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[str]]:
    """The programmatic BOM-to-inventory-consumption path -- "record this
    build" deducts every material line's real stock atomically. Same
    confirm-before-you-commit expectation as inventory's own manual
    /adjust route: the frontend is expected to show the admin exactly
    what will be consumed (fetch the BOM's material lines, multiply by
    build_quantity) before calling this.
    """
    result = await consume_bom(
        db, bom_id, body.build_quantity, admin.user_id, body.reason
    )
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return {"adjustment_ids": [str(i) for i in result.danger_ok]}
