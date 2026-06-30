from __future__ import annotations

from uuid import uuid4

from logand_backend.db.models.inventory import InventoryItem, InventoryLocation
from logand_backend.domain.inventory.service import (
    create_item,
    delete_item,
    move_item,
    search_items,
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
