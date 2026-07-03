from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from logand_backend.db.models.bom import BillOfMaterials, BomMaterialLine
from logand_backend.db.models.inventory import InventoryItem, InventoryLocation
from logand_backend.domain.bom.service import (
    add_material_line,
    compute_cost_breakdown,
    consume_bom,
    create_bom,
    delete_bom,
    get_bom,
    list_boms,
    remove_material_line,
)
from logand_backend.domain.inventory.service import list_item_adjustments
from logand_backend.errors import BomError


async def _make_location(db_session) -> InventoryLocation:
    location = InventoryLocation(id=uuid4(), name=f"shelf-{uuid4()}")
    db_session.add(location)
    await db_session.flush()
    return location


async def _make_item(
    db_session, location, name: str = "widget", unit_cost: str | None = "2.50"
) -> InventoryItem:
    item = InventoryItem(
        id=uuid4(),
        name=name,
        location_id=location.id,
        quantity=100,
        unit_cost=Decimal(unit_cost) if unit_cost is not None else None,
    )
    db_session.add(item)
    await db_session.flush()
    return item


async def test_create_bom(db_session) -> None:
    result = await create_bom(
        db_session,
        "Widget Assembly",
        labor_hours=Decimal("2.0"),
        labor_rate=Decimal("25.00"),
        overhead_percent=Decimal("10.00"),
    )
    assert result.is_ok
    bom = await db_session.get(BillOfMaterials, result.danger_ok)
    assert bom.name == "Widget Assembly"
    assert bom.labor_hours == Decimal("2.0")


async def test_get_bom_not_found(db_session) -> None:
    result = await get_bom(db_session, uuid4())
    assert result.is_err
    assert result.danger_err == BomError.NotFound


async def test_list_boms(db_session) -> None:
    await create_bom(db_session, "A")
    await create_bom(db_session, "B")
    result = await list_boms(db_session)
    assert result.is_ok
    names = {b.name for b in result.danger_ok}
    assert {"A", "B"} <= names


async def test_delete_bom(db_session) -> None:
    bom_id = (await create_bom(db_session, "to delete")).danger_ok
    result = await delete_bom(db_session, bom_id)
    assert result.is_ok
    assert await db_session.get(BillOfMaterials, bom_id) is None


async def test_delete_bom_not_found(db_session) -> None:
    result = await delete_bom(db_session, uuid4())
    assert result.is_err
    assert result.danger_err == BomError.NotFound


async def test_add_material_line(db_session) -> None:
    location = await _make_location(db_session)
    item = await _make_item(db_session, location)
    bom_id = (await create_bom(db_session, "Widget Assembly")).danger_ok

    result = await add_material_line(db_session, bom_id, item.id, quantity_per_unit=3)

    assert result.is_ok
    line = await db_session.get(BomMaterialLine, result.danger_ok)
    assert line.quantity_per_unit == 3


async def test_add_material_line_bom_not_found(db_session) -> None:
    location = await _make_location(db_session)
    item = await _make_item(db_session, location)
    result = await add_material_line(db_session, uuid4(), item.id, 1)
    assert result.is_err
    assert result.danger_err == BomError.NotFound


async def test_add_material_line_item_not_found(db_session) -> None:
    bom_id = (await create_bom(db_session, "x")).danger_ok
    result = await add_material_line(db_session, bom_id, uuid4(), 1)
    assert result.is_err
    assert result.danger_err == BomError.ItemNotFound


async def test_add_material_line_rejects_duplicate_item(db_session) -> None:
    location = await _make_location(db_session)
    item = await _make_item(db_session, location)
    bom_id = (await create_bom(db_session, "x")).danger_ok
    await add_material_line(db_session, bom_id, item.id, 1)

    result = await add_material_line(db_session, bom_id, item.id, 2)

    assert result.is_err
    assert result.danger_err == BomError.DuplicateItem
    # The first line must be untouched -- a rejected duplicate-add must
    # not corrupt the existing line or leave the session in a broken
    # state for whatever the caller does next.
    lines = (
        await db_session.execute(
            BomMaterialLine.__table__.select().where(BomMaterialLine.bom_id == bom_id)
        )
    ).all()
    assert len(lines) == 1


async def test_remove_material_line(db_session) -> None:
    location = await _make_location(db_session)
    item = await _make_item(db_session, location)
    bom_id = (await create_bom(db_session, "x")).danger_ok
    await add_material_line(db_session, bom_id, item.id, 1)

    result = await remove_material_line(db_session, bom_id, item.id)

    assert result.is_ok


async def test_remove_material_line_not_found(db_session) -> None:
    bom_id = (await create_bom(db_session, "x")).danger_ok
    result = await remove_material_line(db_session, bom_id, uuid4())
    assert result.is_err
    assert result.danger_err == BomError.MaterialLineNotFound


async def test_compute_cost_breakdown_real_math(db_session) -> None:
    location = await _make_location(db_session)
    resistor = await _make_item(db_session, location, "resistor", unit_cost="0.10")
    capacitor = await _make_item(db_session, location, "capacitor", unit_cost="0.50")
    bom_id = (
        await create_bom(
            db_session,
            "PCB",
            labor_hours=Decimal("1.0"),
            labor_rate=Decimal("30.00"),
            overhead_percent=Decimal("20.00"),
        )
    ).danger_ok
    await add_material_line(db_session, bom_id, resistor.id, quantity_per_unit=10)
    await add_material_line(db_session, bom_id, capacitor.id, quantity_per_unit=2)

    result = await compute_cost_breakdown(db_session, bom_id, build_quantity=1)

    assert result.is_ok
    breakdown = result.danger_ok
    # material: 10 * 0.10 + 2 * 0.50 = 1.00 + 1.00 = 2.00
    assert breakdown.material_cost == Decimal("2.00")
    # labor: 1.0 hr * 30.00/hr = 30.00
    assert breakdown.labor_cost == Decimal("30.00")
    # overhead: (2.00 + 30.00) * 20% = 6.40
    assert breakdown.overhead_cost == Decimal("6.400")
    # total: 2.00 + 30.00 + 6.40 = 38.40
    assert breakdown.total_cost == Decimal("38.400")
    assert len(breakdown.material_lines) == 2


async def test_compute_cost_breakdown_scales_with_build_quantity(db_session) -> None:
    location = await _make_location(db_session)
    item = await _make_item(db_session, location, unit_cost="1.00")
    bom_id = (
        await create_bom(
            db_session, "x", labor_hours=Decimal("1.0"), labor_rate=Decimal("10.00")
        )
    ).danger_ok
    await add_material_line(db_session, bom_id, item.id, quantity_per_unit=5)

    result = await compute_cost_breakdown(db_session, bom_id, build_quantity=3)

    assert result.is_ok
    breakdown = result.danger_ok
    # 5 units/build * 3 builds * $1.00 = $15.00
    assert breakdown.material_cost == Decimal("15.00")
    # 1.0 hr/build * 3 builds * $10.00/hr = $30.00
    assert breakdown.labor_cost == Decimal("30.00")


async def test_compute_cost_breakdown_missing_unit_cost(db_session) -> None:
    location = await _make_location(db_session)
    item = await _make_item(db_session, location, unit_cost=None)
    bom_id = (await create_bom(db_session, "x")).danger_ok
    await add_material_line(db_session, bom_id, item.id, quantity_per_unit=1)

    result = await compute_cost_breakdown(db_session, bom_id)

    assert result.is_err
    assert result.danger_err == BomError.MissingUnitCost


async def test_compute_cost_breakdown_not_found(db_session) -> None:
    result = await compute_cost_breakdown(db_session, uuid4())
    assert result.is_err
    assert result.danger_err == BomError.NotFound


async def test_compute_cost_breakdown_with_no_material_lines(db_session) -> None:
    # Pure-labor BOM (a service, not a physical build) -- material_cost
    # must be a real zero, not an error, when there simply are no lines.
    bom_id = (
        await create_bom(
            db_session, "labor-only", labor_hours=Decimal("2"), labor_rate=Decimal("50")
        )
    ).danger_ok
    result = await compute_cost_breakdown(db_session, bom_id)
    assert result.is_ok
    assert result.danger_ok.material_cost == Decimal(0)
    assert result.danger_ok.labor_cost == Decimal("100")


async def test_consume_bom_deducts_stock_and_writes_audited_adjustments(
    db_session,
) -> None:
    location = await _make_location(db_session)
    resistor = await _make_item(db_session, location, "resistor")
    capacitor = await _make_item(db_session, location, "capacitor")
    # _make_item defaults quantity=100 (see test_inventory_service.py-
    # style helper above).
    bom_id = (await create_bom(db_session, "PCB")).danger_ok
    await add_material_line(db_session, bom_id, resistor.id, quantity_per_unit=10)
    await add_material_line(db_session, bom_id, capacitor.id, quantity_per_unit=2)

    result = await consume_bom(db_session, bom_id, build_quantity=3, adjusted_by=None)

    assert result.is_ok
    assert len(result.danger_ok) == 2

    resistor_after = await db_session.get(InventoryItem, resistor.id)
    capacitor_after = await db_session.get(InventoryItem, capacitor.id)
    # 100 - (10 * 3) = 70
    assert resistor_after.quantity == 70
    # 100 - (2 * 3) = 94
    assert capacitor_after.quantity == 94

    resistor_adjustments = (
        await list_item_adjustments(db_session, resistor.id)
    ).danger_ok
    assert len(resistor_adjustments) == 1
    assert resistor_adjustments[0].delta == -30
    assert "PCB" in resistor_adjustments[0].reason


async def test_consume_bom_uses_custom_reason_when_given(db_session) -> None:
    location = await _make_location(db_session)
    item = await _make_item(db_session, location)
    bom_id = (await create_bom(db_session, "x")).danger_ok
    await add_material_line(db_session, bom_id, item.id, quantity_per_unit=1)

    await consume_bom(
        db_session, bom_id, build_quantity=1, adjusted_by=None, reason="build #42"
    )

    adjustments = (await list_item_adjustments(db_session, item.id)).danger_ok
    assert adjustments[0].reason == "build #42"


async def test_consume_bom_is_all_or_nothing_when_one_line_lacks_stock(
    db_session,
) -> None:
    location = await _make_location(db_session)
    plentiful = await _make_item(db_session, location, "plentiful")  # quantity=100
    scarce = await _make_item(db_session, location, "scarce")
    scarce.quantity = 5
    await db_session.flush()

    bom_id = (await create_bom(db_session, "x")).danger_ok
    await add_material_line(db_session, bom_id, plentiful.id, quantity_per_unit=1)
    # Needs 10 * 3 = 30, but only 5 in stock.
    await add_material_line(db_session, bom_id, scarce.id, quantity_per_unit=10)

    result = await consume_bom(db_session, bom_id, build_quantity=3, adjusted_by=None)

    assert result.is_err
    assert result.danger_err == BomError.InsufficientStock
    # The critical assertion: plentiful's stock must be COMPLETELY
    # untouched, even though it individually had enough stock and would
    # have succeeded if checked in isolation -- this is exactly what the
    # two-phase check-then-write design (see consume_bom's own doc
    # comment) exists to guarantee.
    plentiful_after = await db_session.get(InventoryItem, plentiful.id)
    assert plentiful_after.quantity == 100
    assert (await list_item_adjustments(db_session, plentiful.id)).danger_ok == []
    scarce_after = await db_session.get(InventoryItem, scarce.id)
    assert scarce_after.quantity == 5


async def test_consume_bom_rejects_negative_build_quantity(db_session) -> None:
    """Regression test for L4: a negative build_quantity makes `need`
    negative, so `item.quantity < need` is always false (the stock check
    always "passes") and the later `-need` adjustment becomes a POSITIVE
    delta -- i.e. a "consumption" that actually adds stock. Must be
    rejected outright before ever reaching that math.
    """
    location = await _make_location(db_session)
    item = await _make_item(db_session, location)  # quantity=100
    bom_id = (await create_bom(db_session, "x")).danger_ok
    await add_material_line(db_session, bom_id, item.id, quantity_per_unit=1)

    result = await consume_bom(db_session, bom_id, build_quantity=-5, adjusted_by=None)

    assert result.is_err
    assert result.danger_err == BomError.InvalidBuildQuantity
    item_after = await db_session.get(InventoryItem, item.id)
    assert item_after.quantity == 100


async def test_consume_bom_rejects_zero_build_quantity(db_session) -> None:
    location = await _make_location(db_session)
    item = await _make_item(db_session, location)
    bom_id = (await create_bom(db_session, "x")).danger_ok
    await add_material_line(db_session, bom_id, item.id, quantity_per_unit=1)

    result = await consume_bom(db_session, bom_id, build_quantity=0, adjusted_by=None)

    assert result.is_err
    assert result.danger_err == BomError.InvalidBuildQuantity


async def test_consume_bom_not_found(db_session) -> None:
    result = await consume_bom(db_session, uuid4(), build_quantity=1, adjusted_by=None)
    assert result.is_err
    assert result.danger_err == BomError.NotFound


async def test_consume_bom_with_no_material_lines_succeeds_trivially(
    db_session,
) -> None:
    # A pure-labor BOM (no material lines at all) has nothing to check or
    # deduct -- must succeed with an empty adjustment list, not error.
    bom_id = (await create_bom(db_session, "labor-only")).danger_ok
    result = await consume_bom(db_session, bom_id, build_quantity=5, adjusted_by=None)
    assert result.is_ok
    assert result.danger_ok == []
