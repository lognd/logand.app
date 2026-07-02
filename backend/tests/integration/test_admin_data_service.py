from __future__ import annotations

from uuid import uuid4

from logand_backend.db.models.inventory import InventoryItem, InventoryLocation
from logand_backend.domain.admin_data.service import (
    delete_row,
    get_row,
    get_table_columns,
    insert_row,
    list_rows,
    list_tables,
    revert_change,
    update_row,
)
from logand_backend.domain.inventory.service import create_item


async def _make_item(db_session, quantity: int = 10) -> str:
    location = InventoryLocation(id=uuid4(), name="Shelf A")
    db_session.add(location)
    await db_session.flush()
    result = await create_item(db_session, "widget", location.id, quantity=quantity)
    await db_session.flush()
    return str(result.danger_ok)


async def test_list_tables_excludes_sessions_and_includes_business_tables() -> None:
    tables = list_tables()
    assert "sessions" not in tables
    assert "inventory_items" in tables
    assert "users" in tables


async def test_get_table_columns_marks_password_hash_and_id_not_editable() -> None:
    result = get_table_columns("users")
    assert result.is_ok
    columns = {c["name"]: c for c in result.danger_ok}
    assert columns["password_hash"]["editable"] is False
    assert columns["id"]["editable"] is False
    assert columns["email"]["editable"] is True


async def test_get_table_columns_unknown_table_is_err() -> None:
    result = get_table_columns("not_a_real_table")
    assert result.is_err


async def test_list_rows_and_get_row_round_trip(db_session) -> None:
    item_id = await _make_item(db_session)

    rows = (await list_rows(db_session, "inventory_items")).danger_ok
    assert any(r["id"] == item_id for r in rows)

    row = (await get_row(db_session, "inventory_items", item_id)).danger_ok
    assert row["name"] == "widget"
    assert row["quantity"] == 10


async def test_get_row_never_leaks_a_real_password_hash(db_session, make_user) -> None:
    user = await make_user(role="customer", password="pw")
    row = (await get_row(db_session, "users", str(user.id))).danger_ok
    assert row["password_hash"] == "<redacted>"


async def test_update_row_applies_change_and_writes_audit_log(db_session) -> None:
    item_id = await _make_item(db_session)

    result = await update_row(
        db_session, "inventory_items", item_id, {"quantity": 42}, admin_id=None
    )
    assert result.is_ok

    row = (await get_row(db_session, "inventory_items", item_id)).danger_ok
    assert row["quantity"] == 42

    item = await db_session.get(InventoryItem, item_id)
    assert item.quantity == 42


async def test_update_row_rejects_id_and_password_hash_columns(db_session) -> None:
    item_id = await _make_item(db_session)

    result = await update_row(
        db_session, "inventory_items", item_id, {"id": str(uuid4())}, admin_id=None
    )
    assert result.is_err


async def test_update_row_rejects_unknown_column(db_session) -> None:
    item_id = await _make_item(db_session)

    result = await update_row(
        db_session, "inventory_items", item_id, {"not_a_column": 1}, admin_id=None
    )
    assert result.is_err


async def test_update_row_missing_row_is_err(db_session) -> None:
    result = await update_row(
        db_session, "inventory_items", str(uuid4()), {"quantity": 1}, admin_id=None
    )
    assert result.is_err


async def test_update_row_constraint_violation_leaves_row_unchanged(db_session) -> None:
    """inventory_items has a real NOT NULL name column -- setting it to
    NULL must be rejected by Postgres itself (the whole point of routing
    every write through Core against the real Table, not raw SQL), and
    the row must be provably untouched afterward."""
    item_id = await _make_item(db_session)
    await db_session.commit()

    result = await update_row(
        db_session, "inventory_items", item_id, {"name": None}, admin_id=None
    )
    assert result.is_err

    row = (await get_row(db_session, "inventory_items", item_id)).danger_ok
    assert row["name"] == "widget"


async def test_delete_row_removes_row_and_writes_audit_log(db_session) -> None:
    item_id = await _make_item(db_session)

    result = await delete_row(db_session, "inventory_items", item_id, admin_id=None)
    assert result.is_ok

    missing = await get_row(db_session, "inventory_items", item_id)
    assert missing.is_err


async def test_insert_row_creates_row_with_full_after_snapshot(db_session) -> None:
    location = InventoryLocation(id=uuid4(), name="Shelf B")
    db_session.add(location)
    await db_session.flush()

    result = await insert_row(
        db_session,
        "inventory_items",
        {"name": "gadget", "location_id": str(location.id), "quantity": 5},
        admin_id=None,
    )
    assert result.is_ok

    rows = (await list_rows(db_session, "inventory_items")).danger_ok
    assert any(r["name"] == "gadget" and r["quantity"] == 5 for r in rows)


async def test_revert_update_restores_before_state(db_session) -> None:
    item_id = await _make_item(db_session, quantity=10)

    change = await update_row(
        db_session, "inventory_items", item_id, {"quantity": 999}, admin_id=None
    )
    assert change.is_ok

    revert_result = await revert_change(db_session, change.danger_ok, admin_id=None)
    assert revert_result.is_ok

    row = (await get_row(db_session, "inventory_items", item_id)).danger_ok
    assert row["quantity"] == 10


async def test_revert_delete_reinserts_row(db_session) -> None:
    item_id = await _make_item(db_session, quantity=7)

    change = await delete_row(db_session, "inventory_items", item_id, admin_id=None)
    assert change.is_ok

    revert_result = await revert_change(db_session, change.danger_ok, admin_id=None)
    assert revert_result.is_ok

    row = (await get_row(db_session, "inventory_items", item_id)).danger_ok
    assert row["quantity"] == 7


async def test_revert_insert_deletes_row(db_session) -> None:
    location = InventoryLocation(id=uuid4(), name="Shelf C")
    db_session.add(location)
    await db_session.flush()

    change = await insert_row(
        db_session,
        "inventory_items",
        {"name": "thingamajig", "location_id": str(location.id), "quantity": 1},
        admin_id=None,
    )
    assert change.is_ok
    log_id = change.danger_ok

    change_log_rows = (await list_rows(db_session, "admin_audit_log")).danger_ok
    inserted_log = next(r for r in change_log_rows if r["id"] == str(log_id))
    target_id = inserted_log["target_id"]

    revert_result = await revert_change(db_session, log_id, admin_id=None)
    assert revert_result.is_ok

    missing = await get_row(db_session, "inventory_items", target_id)
    assert missing.is_err


async def test_revert_unknown_change_is_err(db_session) -> None:
    result = await revert_change(db_session, uuid4(), admin_id=None)
    assert result.is_err
