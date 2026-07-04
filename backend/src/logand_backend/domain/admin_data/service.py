from __future__ import annotations

import decimal
import uuid
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Table, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.base import Base
from logand_backend.db.models.audit import AdminAuditLog
from logand_backend.errors import DataError

# "Absolute power" over real business data, per the user's own explicit
# scope decision -- genuinely any table, via reflection over
# Base.metadata (see conftest.py's own db_engine fixture doc comment on
# why every model MUST be imported through db/models/__init__.py for
# this to see them all), not a hand-maintained per-table allowlist.
#
# TWO deliberate exceptions, both because the user's OWN stated
# requirement was "at no point can ANYTHING be in an INVALID/CORRUPT
# STATE" -- these two are cases where a technically-DB-constraint-valid
# write would still leave the system in a functionally broken/insecure
# state that Postgres's own constraints can't catch:
#   - "sessions" table excluded entirely -- a session row IS a live,
#     currently-valid authentication credential; hand-editing or forging
#     one is a security bypass, not a data-correction, and doesn't fit
#     "browse/fix business data" at all.
#   - "password_hash" column excluded on every table it appears on -- a
#     raw string written here isn't a valid argon2 hash, so the account
#     becomes permanently unable to log in even though nothing about that
#     write violates any DB constraint. Real password resets go through
#     domain/users/service.py::admin_reset_password, which hashes
#     properly; this tool intentionally can't bypass that.
_EXCLUDED_TABLES = {"sessions"}
_NEVER_EDITABLE_COLUMNS = {"id", "password_hash"}


def list_tables() -> list[str]:
    return sorted(name for name in Base.metadata.tables if name not in _EXCLUDED_TABLES)


def _get_table(table_name: str) -> Table | None:
    if table_name in _EXCLUDED_TABLES:
        return None
    return Base.metadata.tables.get(table_name)


def _validate_row_id(row_id: str) -> DataError | None:
    """Every admin_data table's `id` column is a UUID -- a `row_id` that
    isn't a valid UUID would otherwise reach Postgres as a raw string
    compared against a UUID column, which raises at the DB level (an
    uncaught 500) instead of the intended RowNotFound (404). Reject it
    here, before any query runs."""
    try:
        uuid.UUID(row_id)
    except ValueError:
        return DataError.RowNotFound
    return None


def get_table_columns(table_name: str) -> Result[list[dict], DataError]:
    table = _get_table(table_name)
    if table is None:
        return Err(DataError.TableNotFound)
    return Ok(
        [
            {
                "name": col.name,
                "type": str(col.type),
                "nullable": col.nullable,
                "primary_key": col.primary_key,
                "editable": col.name not in _NEVER_EDITABLE_COLUMNS,
            }
            for col in table.columns
        ]
    )


def _serialize_value(value: Any) -> Any:
    """JSON-safe, and this is also the ONE place that redacts
    password_hash-shaped values if a caller ever forgets to strip the
    column first -- belt and suspenders, since AdminAuditLog snapshots
    must never contain a real hash (see that model's own doc comment)."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    return value


def _serialize_row(table: Table, row: Any) -> dict:
    result = {}
    for col in table.columns:
        value = getattr(row, col.name)
        if col.name == "password_hash":
            result[col.name] = "<redacted>"
        else:
            result[col.name] = _serialize_value(value)
    return result


async def list_rows(
    db: AsyncSession, table_name: str, limit: int = 50, offset: int = 0
) -> Result[list[dict], DataError]:
    table = _get_table(table_name)
    if table is None:
        return Err(DataError.TableNotFound)
    limit = max(1, min(limit, 200))
    # ORDER BY id -- without one, Postgres makes no row-order guarantee at
    # all, so paging through a table with LIMIT/OFFSET alone can skip or
    # repeat rows as concurrent writes land between pages (see FINDINGS.md
    # L4). Primary key is stable and every admin_data table has one.
    rows = (
        await db.execute(
            select(table).order_by(table.c.id).limit(limit).offset(max(0, offset))
        )
    ).all()
    return Ok([_serialize_row(table, row) for row in rows])


async def get_row(
    db: AsyncSession, table_name: str, row_id: str
) -> Result[dict, DataError]:
    table = _get_table(table_name)
    if table is None:
        return Err(DataError.TableNotFound)
    invalid_id = _validate_row_id(row_id)
    if invalid_id is not None:
        return Err(invalid_id)
    row = (await db.execute(select(table).where(table.c.id == row_id))).first()
    if row is None:
        return Err(DataError.RowNotFound)
    return Ok(_serialize_row(table, row))


def _validate_changes(
    table: Table,
    changes: dict,
    forbidden: frozenset[str] = frozenset(_NEVER_EDITABLE_COLUMNS),
) -> DataError | None:
    valid_columns = set(table.columns.keys())
    for key in changes:
        if key not in valid_columns:
            return DataError.ColumnNotFound
        if key in forbidden:
            return DataError.ColumnNotEditable
    return None


def _coerce_value(table: Table, key: str, value: Any) -> Any:
    """Snapshots stored in AdminAuditLog (and therefore fed back in by
    revert_change) went through _serialize_value above -- datetimes and
    Decimals became plain strings there so they're JSON-safe in the
    JSONB column. This is the inverse, so a reverted UPDATE/INSERT gets
    real Python objects back, not strings the DBAPI driver rejects."""
    if value is None:
        return None
    col_type = table.c[key].type
    python_type = getattr(col_type, "python_type", None)
    if python_type in (datetime,) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if python_type in (date,) and isinstance(value, str):
        return date.fromisoformat(value)
    if python_type in (decimal.Decimal,) and isinstance(value, str):
        return decimal.Decimal(value)
    return value


async def update_row(
    db: AsyncSession,
    table_name: str,
    row_id: str,
    changes: dict,
    admin_id: UUID | None,
) -> Result[UUID, DataError]:
    """The core "absolute power, but never a corrupt state" write path:
    real UPDATE through SQLAlchemy Core against the reflected Table (so
    every NOT NULL/CHECK/FK/UNIQUE constraint Postgres itself enforces
    still applies -- this never bypasses them), row-locked for the
    duration (FOR UPDATE) so a concurrent write to the same row can't
    interleave with this one, and a full before/after snapshot written
    to AdminAuditLog BEFORE returning -- that snapshot is the real
    rollback record (see revert_change).
    """
    table = _get_table(table_name)
    if table is None:
        return Err(DataError.TableNotFound)
    invalid_id = _validate_row_id(row_id)
    if invalid_id is not None:
        return Err(invalid_id)
    invalid = _validate_changes(table, changes)
    if invalid is not None:
        return Err(invalid)

    current = (
        await db.execute(select(table).where(table.c.id == row_id).with_for_update())
    ).first()
    if current is None:
        return Err(DataError.RowNotFound)
    before = _serialize_row(table, current)
    coerced_changes = {k: _coerce_value(table, k, v) for k, v in changes.items()}

    try:
        await db.execute(
            update(table).where(table.c.id == row_id).values(**coerced_changes)
        )
        await db.flush()
    except IntegrityError:
        # Safe to roll back HERE specifically (unlike, say,
        # domain/bom/service.py's add_material_line, which composes with
        # other writes in the same request) -- this is always the ONLY
        # write in whatever request called it, so there is nothing else
        # in this transaction a rollback could discard.
        await db.rollback()
        return Err(DataError.ConstraintViolation)

    after_row = (await db.execute(select(table).where(table.c.id == row_id))).first()
    after = _serialize_row(table, after_row)

    log_id = uuid4()
    if before == after:
        # Every column ended up equal to its starting value (e.g. a
        # no-op edit submitted unchanged) -- writing a real "data.update"
        # audit entry here would be indistinguishable from a genuine
        # change, and revert_change on it is a silent no-op that still
        # LOOKS like a real revert in the log (FINDINGS.md L3). Tag it
        # distinctly instead of skipping the audit trail entirely, so
        # the row-level edit still leaves a record that it happened.
        db.add(
            AdminAuditLog(
                id=log_id,
                admin_id=admin_id,
                action="data.update.noop",
                target_table=table_name,
                target_id=row_id,
                before_state=before,
                after_state=after,
            )
        )
        await db.flush()
        return Ok(log_id)

    db.add(
        AdminAuditLog(
            id=log_id,
            admin_id=admin_id,
            action="data.update",
            target_table=table_name,
            target_id=row_id,
            before_state=before,
            after_state=after,
        )
    )
    await db.flush()
    return Ok(log_id)


async def delete_row(
    db: AsyncSession, table_name: str, row_id: str, admin_id: UUID | None
) -> Result[UUID, DataError]:
    table = _get_table(table_name)
    if table is None:
        return Err(DataError.TableNotFound)
    invalid_id = _validate_row_id(row_id)
    if invalid_id is not None:
        return Err(invalid_id)

    current = (
        await db.execute(select(table).where(table.c.id == row_id).with_for_update())
    ).first()
    if current is None:
        return Err(DataError.RowNotFound)
    before = _serialize_row(table, current)

    try:
        await db.execute(delete(table).where(table.c.id == row_id))
        await db.flush()
    except IntegrityError:
        # A real, expected case -- deleting a row another table still
        # references via a RESTRICT foreign key (e.g. an inventory_item
        # a BOM material line still points at). Rejected loudly, exactly
        # the "never a corrupt state" guarantee: this never silently
        # cascades or orphans anything beyond what each FK's own
        # ondelete= already specifies.
        await db.rollback()
        return Err(DataError.ConstraintViolation)

    log_id = uuid4()
    db.add(
        AdminAuditLog(
            id=log_id,
            admin_id=admin_id,
            action="data.delete",
            target_table=table_name,
            target_id=row_id,
            before_state=before,
            after_state=None,
        )
    )
    await db.flush()
    return Ok(log_id)


async def insert_row(
    db: AsyncSession, table_name: str, values: dict, admin_id: UUID | None
) -> Result[UUID, DataError]:
    table = _get_table(table_name)
    if table is None:
        return Err(DataError.TableNotFound)
    # Unlike update_row, "id" is allowed here -- it's the one column an
    # INSERT legitimately needs to set (e.g. reverting a delete must
    # reinsert with the SAME id, not a fresh one). password_hash stays
    # forbidden either way.
    invalid = _validate_changes(table, values, forbidden=frozenset({"password_hash"}))
    if invalid is not None:
        return Err(invalid)

    supplied_id = values.get("id")
    if supplied_id:
        invalid_id = _validate_row_id(str(supplied_id))
        if invalid_id is not None:
            return Err(DataError.ConstraintViolation)
        new_id = supplied_id
    else:
        new_id = str(uuid4())
    coerced_values = {
        k: _coerce_value(table, k, v) for k, v in values.items() if k != "id"
    }
    try:
        await db.execute(insert(table).values(**coerced_values, id=new_id))
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return Err(DataError.ConstraintViolation)

    new_row = (await db.execute(select(table).where(table.c.id == new_id))).first()
    after = _serialize_row(table, new_row)

    log_id = uuid4()
    db.add(
        AdminAuditLog(
            id=log_id,
            admin_id=admin_id,
            action="data.insert",
            target_table=table_name,
            target_id=str(new_id),
            before_state=None,
            after_state=after,
        )
    )
    await db.flush()
    return Ok(log_id)


async def revert_change(
    db: AsyncSession, log_id: UUID, admin_id: UUID | None
) -> Result[UUID, DataError]:
    """Reverts one AdminAuditLog entry by replaying it backwards through
    the SAME validated write paths above -- never a raw UPDATE/INSERT/
    DELETE bypassing them, so a revert is exactly as constraint-safe as
    the original write was.

    - data.update  -> update_row back to before_state
    - data.delete  -> insert_row using before_state (un-delete)
    - data.insert  -> delete_row (un-insert)

    before_state/after_state snapshots always carry EVERY column,
    including the never-editable ones (id, password_hash -- see
    _serialize_row) -- password_hash in particular is always the literal
    string "<redacted>", never a real hash. Both replay branches below
    filter _NEVER_EDITABLE_COLUMNS out of what they hand to update_row/
    insert_row: those two functions reject any attempt to WRITE one of
    those columns (by design -- see their own docstrings), so passing
    "id"/"password_hash" straight through here would make every revert
    of a row that has a password_hash column (i.e. every users-table
    revert) fail outright, even when nothing about password_hash itself
    ever changed. The one real, permanent limitation this can't paper
    over: un-deleting a users row can never restore its actual
    password_hash (only "<redacted>" was ever recorded) -- that revert
    still fails, now via a real NOT NULL constraint violation
    (DataError.ConstraintViolation) instead of a misleading "column not
    editable," since password_hash has no default and can't be left out
    of a real INSERT. A locked-out account restored this way needs
    admin_reset_password to actually become loginable again.
    """
    log = await db.get(AdminAuditLog, log_id)
    if log is None:
        return Err(DataError.ChangeNotFound)
    if log.target_table is None or log.target_id is None:
        return Err(DataError.ChangeNotRevertible)

    if log.action == "data.update":
        if log.before_state is None:
            return Err(DataError.ChangeNotRevertible)
        changes = {
            k: v
            for k, v in log.before_state.items()
            if k not in _NEVER_EDITABLE_COLUMNS
        }
        result = await update_row(
            db, log.target_table, log.target_id, changes, admin_id
        )
    elif log.action == "data.delete":
        if log.before_state is None:
            return Err(DataError.ChangeNotRevertible)
        values = {
            k: v
            for k, v in log.before_state.items()
            if k not in _NEVER_EDITABLE_COLUMNS
        }
        # "id" IS allowed on insert (see insert_row's own doc comment --
        # an un-delete must reinsert with the SAME id, not a fresh one),
        # unlike password_hash, which stays excluded either way.
        if "id" in log.before_state:
            values["id"] = log.before_state["id"]
        result = await insert_row(db, log.target_table, values, admin_id)
    elif log.action == "data.insert":
        result = await delete_row(db, log.target_table, log.target_id, admin_id)
    elif log.action == "data.update.noop":
        # Per L2 in FINDINGS.md: a no-op edit was never a real change, so
        # reverting it is trivially a no-op too -- return success without
        # touching the row or writing another audit entry, rather than the
        # misleading ChangeNotRevertible (which reads to an admin as "this
        # failed" when nothing needed to happen in the first place).
        # Per L1 in FINDINGS.md: return the id of the entry being reverted
        # (log_id), NOT log.target_id -- target_id is the edited business
        # row's id, not an AdminAuditLog id, and every other branch here
        # returns a real AdminAuditLog id that the caller can look up via
        # GET /api/admin/data/changes/{change_id}.
        return Ok(log_id)
    else:
        return Err(DataError.ChangeNotRevertible)

    if result.is_err:
        return result

    revert_log_id = uuid4()
    db.add(
        AdminAuditLog(
            id=revert_log_id,
            admin_id=admin_id,
            action="data.revert",
            target_table=log.target_table,
            target_id=log.target_id,
            before_state=log.after_state,
            after_state=log.before_state,
        )
    )
    await db.flush()
    # Per L1 in FINDINGS.md: return the "data.revert" entry's own id, not
    # the replayed write's (update_row/insert_row/delete_row) audit id --
    # a caller looking this id up via GET /changes/{id} must see the
    # revert entry itself, matching the data.update.noop branch's
    # contract above.
    return Ok(revert_log_id)
