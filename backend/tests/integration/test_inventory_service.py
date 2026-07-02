from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from logand_backend.db.models.inventory import InventoryItem, InventoryLocation
from logand_backend.domain.inventory.service import (
    adjust_item_quantity,
    create_item,
    delete_item,
    list_item_adjustments,
    move_item,
    search_items,
    set_item_unit_cost,
    update_item_quantity,
)
from logand_backend.errors import InventoryError


async def _make_location(db_session, name: str = "shelf") -> InventoryLocation:
    location = InventoryLocation(id=uuid4(), name=f"{name}-{uuid4()}")
    db_session.add(location)
    await db_session.flush()
    return location


async def test_create_item(db_session) -> None:
    location = await _make_location(db_session)

    result = await create_item(
        db_session, "resistor", location.id, quantity=10, tags=["electronics"]
    )

    assert result.is_ok
    item = await db_session.get(InventoryItem, result.danger_ok)
    assert item.name == "resistor"
    assert item.quantity == 10
    assert item.tags == ["electronics"]


async def test_move_item(db_session) -> None:
    location_a = await _make_location(db_session, "a")
    location_b = await _make_location(db_session, "b")
    item_id = (await create_item(db_session, "widget", location_a.id)).danger_ok

    result = await move_item(db_session, item_id, location_b.id)

    assert result.is_ok
    item = await db_session.get(InventoryItem, item_id)
    assert item.location_id == location_b.id


async def test_move_item_not_found(db_session) -> None:
    location = await _make_location(db_session)
    result = await move_item(db_session, uuid4(), location.id)
    assert result.is_err
    assert result.danger_err == InventoryError.NotFound


async def test_update_item_quantity(db_session) -> None:
    location = await _make_location(db_session)
    item_id = (
        await create_item(db_session, "widget", location.id, quantity=1)
    ).danger_ok

    result = await update_item_quantity(db_session, item_id, 99)

    assert result.is_ok
    item = await db_session.get(InventoryItem, item_id)
    assert item.quantity == 99


async def test_delete_item(db_session) -> None:
    location = await _make_location(db_session)
    item_id = (await create_item(db_session, "widget", location.id)).danger_ok

    result = await delete_item(db_session, item_id)

    assert result.is_ok
    assert await db_session.get(InventoryItem, item_id) is None


async def test_delete_item_not_found(db_session) -> None:
    result = await delete_item(db_session, uuid4())
    assert result.is_err
    assert result.danger_err == InventoryError.NotFound


async def test_search_items_by_location_id(db_session) -> None:
    location_a = await _make_location(db_session, "a")
    location_b = await _make_location(db_session, "b")
    await create_item(db_session, "in-a", location_a.id)
    await create_item(db_session, "in-b", location_b.id)

    result = await search_items(db_session, location_id=location_a.id)

    assert result.is_ok
    names = {item.name for item in result.danger_ok}
    assert names == {"in-a"}


async def test_search_items_by_tag(db_session) -> None:
    location = await _make_location(db_session)
    await create_item(db_session, "tagged", location.id, tags=["rare"])
    await create_item(db_session, "untagged", location.id, tags=[])

    result = await search_items(db_session, tag="rare")

    assert result.is_ok
    names = {item.name for item in result.danger_ok}
    assert names == {"tagged"}


async def test_adjust_item_quantity_restock_increases_and_records_audit_row(
    db_session,
) -> None:
    location = await _make_location(db_session)
    item_id = (
        await create_item(db_session, "widget", location.id, quantity=5)
    ).danger_ok

    result = await adjust_item_quantity(
        db_session, item_id, delta=3, reason="restocked from supplier", adjusted_by=None
    )

    assert result.is_ok
    item = await db_session.get(InventoryItem, item_id)
    assert item.quantity == 8

    adjustments = (await list_item_adjustments(db_session, item_id)).danger_ok
    assert len(adjustments) == 1
    adj = adjustments[0]
    assert adj.delta == 3
    assert adj.quantity_before == 5
    assert adj.quantity_after == 8
    assert adj.reason == "restocked from supplier"


async def test_adjust_item_quantity_negative_delta_decreases(db_session) -> None:
    location = await _make_location(db_session)
    item_id = (
        await create_item(db_session, "widget", location.id, quantity=10)
    ).danger_ok

    result = await adjust_item_quantity(
        db_session, item_id, delta=-4, reason="sold 4 units", adjusted_by=None
    )

    assert result.is_ok
    item = await db_session.get(InventoryItem, item_id)
    assert item.quantity == 6


async def test_adjust_item_quantity_rejects_going_negative(db_session) -> None:
    location = await _make_location(db_session)
    item_id = (
        await create_item(db_session, "widget", location.id, quantity=2)
    ).danger_ok

    result = await adjust_item_quantity(
        db_session, item_id, delta=-5, reason="oops", adjusted_by=None
    )

    assert result.is_err
    assert result.danger_err == InventoryError.WouldGoNegative
    # Quantity and audit trail must both be untouched -- a rejected
    # adjustment must not leave a partial/phantom record behind.
    item = await db_session.get(InventoryItem, item_id)
    assert item.quantity == 2
    assert (await list_item_adjustments(db_session, item_id)).danger_ok == []


async def test_adjust_item_quantity_not_found(db_session) -> None:
    result = await adjust_item_quantity(
        db_session, uuid4(), delta=1, reason="x", adjusted_by=None
    )
    assert result.is_err
    assert result.danger_err == InventoryError.NotFound


async def test_list_item_adjustments_orders_newest_first(db_session) -> None:
    location = await _make_location(db_session)
    item_id = (
        await create_item(db_session, "widget", location.id, quantity=10)
    ).danger_ok
    await db_session.commit()

    # created_at uses Postgres's now() (fixed for the whole transaction,
    # not per-statement) -- three adjustments inside ONE transaction
    # would all get the exact same timestamp, making "newest first"
    # genuinely ambiguous rather than just theoretically so. Committing
    # between each one starts a fresh transaction (and a fresh now())
    # for the next, so the ordering this test asserts is real, not
    # coincidental insertion order.
    await adjust_item_quantity(
        db_session, item_id, delta=1, reason="a", adjusted_by=None
    )
    await db_session.commit()
    await adjust_item_quantity(
        db_session, item_id, delta=2, reason="b", adjusted_by=None
    )
    await db_session.commit()
    await adjust_item_quantity(
        db_session, item_id, delta=3, reason="c", adjusted_by=None
    )
    await db_session.commit()

    adjustments = (await list_item_adjustments(db_session, item_id)).danger_ok
    assert [a.reason for a in adjustments] == ["c", "b", "a"]


async def test_list_item_adjustments_not_found(db_session) -> None:
    result = await list_item_adjustments(db_session, uuid4())
    assert result.is_err
    assert result.danger_err == InventoryError.NotFound


async def test_set_item_unit_cost(db_session) -> None:
    location = await _make_location(db_session)
    item_id = (await create_item(db_session, "widget", location.id)).danger_ok

    result = await set_item_unit_cost(db_session, item_id, Decimal("4.25"))

    assert result.is_ok
    item = await db_session.get(InventoryItem, item_id)
    assert item.unit_cost == Decimal("4.25")


async def test_set_item_unit_cost_not_found(db_session) -> None:
    result = await set_item_unit_cost(db_session, uuid4(), Decimal("1.00"))
    assert result.is_err
    assert result.danger_err == InventoryError.NotFound


async def test_create_item_with_unit_cost(db_session) -> None:
    location = await _make_location(db_session)
    result = await create_item(
        db_session, "widget", location.id, unit_cost=Decimal("9.99")
    )
    assert result.is_ok
    item = await db_session.get(InventoryItem, result.danger_ok)
    assert item.unit_cost == Decimal("9.99")


async def test_search_items_by_free_text_query(db_session) -> None:
    # Exercises the generated search_vector column applied by the
    # _INVENTORY_FTS_DDL conftest fixture (see conftest.py's db_engine).
    location = await _make_location(db_session)
    await create_item(
        db_session, "Arduino Nano", location.id, description="microcontroller board"
    )
    await create_item(db_session, "soldering iron", location.id, description="tool")

    result = await search_items(db_session, query="microcontroller")

    assert result.is_ok
    names = {item.name for item in result.danger_ok}
    assert names == {"Arduino Nano"}
