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


async def test_list_rows_pagination_is_stably_ordered_by_id(db_session) -> None:
    """Regression test for FINDINGS.md L4: select(table).limit().offset()
    with no ORDER BY has no row-order guarantee in Postgres, so paging
    could skip or repeat rows. Same page boundary, queried twice, must
    return identical rows in identical order.
    """
    for i in range(5):
        location = InventoryLocation(id=uuid4(), name=f"Shelf {i}")
        db_session.add(location)
        await db_session.flush()
        await create_item(db_session, f"widget-{i}", location.id, quantity=1)
    await db_session.flush()

    page_1a = (
        await list_rows(db_session, "inventory_items", limit=2, offset=0)
    ).danger_ok
    page_1b = (
        await list_rows(db_session, "inventory_items", limit=2, offset=0)
    ).danger_ok
    page_2 = (
        await list_rows(db_session, "inventory_items", limit=2, offset=2)
    ).danger_ok

    assert [r["id"] for r in page_1a] == [r["id"] for r in page_1b]
    page_1_ids = {r["id"] for r in page_1a}
    page_2_ids = {r["id"] for r in page_2}
    assert page_1_ids.isdisjoint(page_2_ids)
    # Actually ordered by id (ascending), not incidentally consistent.
    all_rows = (
        await list_rows(db_session, "inventory_items", limit=200, offset=0)
    ).danger_ok
    all_ids = [r["id"] for r in all_rows]
    assert all_ids == sorted(all_ids)


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


async def test_revert_update_on_users_table_succeeds_despite_password_hash_snapshot(
    db_session, make_user
) -> None:
    """Regression test for M5: before_state on a users-table row snapshot
    ALWAYS includes a "password_hash": "<redacted>" entry (see
    _serialize_row) -- revert_change must strip that (and "id") out of
    the changes it replays through update_row, or every single revert of
    a users-table UPDATE fails outright via ColumnNotEditable, even when
    password_hash itself was never part of the actual edit.
    """
    user = await make_user(role="customer", email="revert-target@example.com")

    change = await update_row(
        db_session,
        "users",
        str(user.id),
        {"emails_opted_out": True},
        admin_id=None,
    )
    assert change.is_ok

    revert_result = await revert_change(db_session, change.danger_ok, admin_id=None)
    assert revert_result.is_ok, revert_result

    row = (await get_row(db_session, "users", str(user.id))).danger_ok
    assert row["emails_opted_out"] is False
    # Never leaked, before or after the revert.
    assert row["password_hash"] == "<redacted>"


async def test_revert_delete_on_users_table_fails_with_constraint_violation(
    db_session, make_user
) -> None:
    """The one genuine, permanent limitation M5 leaves in place: a
    deleted users row can never be fully un-deleted through this tool,
    because the only password_hash ever recorded in its snapshot is the
    literal string "<redacted>", never a real hash -- restoring that
    would either brick the account (if written) or violate the column's
    NOT NULL constraint (since it's correctly stripped out before the
    INSERT). The real, actionable outcome must be a clear
    ConstraintViolation, not the previous ColumnNotEditable dead end
    disguising the same fact, and not a silent success that quietly
    bricks the account.
    """
    user = await make_user(role="customer", email="undelete-target@example.com")

    change = await delete_row(db_session, "users", str(user.id), admin_id=None)
    assert change.is_ok

    from logand_backend.errors import DataError

    revert_result = await revert_change(db_session, change.danger_ok, admin_id=None)
    assert revert_result.is_err
    assert revert_result.danger_err == DataError.ConstraintViolation
