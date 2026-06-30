from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Result

from logand_backend.errors import BudgetError


async def create_entry(
    db: AsyncSession, amount: Decimal, category: str, occurred_on: date, vendor: str | None = None, memo: str | None = None
) -> Result[UUID, BudgetError]:
    raise NotImplementedError("insert budget_entries row; needs db.models.budget")


async def attach_evidence(db: AsyncSession, entry_id: UUID, file_bytes: bytes, file_path: str) -> Result[UUID, BudgetError]:
    """Computes file_hash server-side and stores it alongside the file path
    so the hash can never disagree with what was actually uploaded."""
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    raise NotImplementedError(
        f"persist file at {file_path} (volume, see docs/design/11) and insert "
        f"budget_entry_evidence row with file_hash={file_hash!r}; needs db.models.budget"
    )


async def correct_entry(
    db: AsyncSession,
    entry_id: UUID,
    *,
    amount: Decimal | None = None,
    category: str | None = None,
    occurred_on: date | None = None,
    vendor: str | None = None,
) -> Result[UUID, BudgetError]:
    """Implements the correction-not-overwrite invariant from
    docs/design/05: once an entry has evidence attached, editing it must
    never mutate the original row in place. Instead this soft-deletes the
    original and inserts a new row with corrects_entry_id pointing back to
    it, so an auditor can always see both the original and the correction.

    This is the one piece of domain logic in this module worth writing for
    real rather than NotImplementedError -- it's a load-bearing invariant,
    not boilerplate CRUD, and the *shape* of the logic doesn't depend on the
    db.models.budget classes existing yet (only the actual row I/O does).
    """
    has_evidence = await _entry_has_evidence(db, entry_id)
    if has_evidence is None:
        return Err(BudgetError.NotFound)

    if not has_evidence:
        raise NotImplementedError("direct in-place update; needs db.models.budget")

    # NOTE: this branch is the actual invariant -- do not "simplify" it back
    # to an UPDATE later just because it looks like duplicate work with the
    # no-evidence branch above. The whole point is that these two paths must
    # never converge.
    new_id = uuid4()
    raise NotImplementedError(
        f"soft-delete {entry_id} (deleted_at=now), insert new row {new_id} "
        "with corrects_entry_id=entry_id and the supplied field overrides; "
        "needs db.models.budget"
    )


async def _entry_has_evidence(db: AsyncSession, entry_id: UUID) -> bool | None:
    """Returns None if entry_id doesn't exist, else whether it has >=1
    evidence row attached. Split out so correct_entry's branch logic above
    is testable independent of the not-yet-implemented write paths."""
    raise NotImplementedError("query budget_entry_evidence count for entry_id; needs db.models.budget")
