from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.models.budget import BudgetEntry, BudgetEntryEvidence
from logand_backend.errors import BudgetError


async def create_entry(
    db: AsyncSession,
    amount: Decimal,
    category: str,
    occurred_on: date,
    vendor: str | None = None,
    memo: str | None = None,
) -> Result[UUID, BudgetError]:
    entry_id = uuid4()
    db.add(
        BudgetEntry(
            id=entry_id,
            amount=amount,
            category=category,
            occurred_on=occurred_on,
            vendor=vendor,
            memo=memo,
        )
    )
    await db.flush()
    return Ok(entry_id)


async def attach_evidence(
    db: AsyncSession, entry_id: UUID, file_bytes: bytes, file_path: str
) -> Result[UUID, BudgetError]:
    """Computes file_hash server-side and stores it alongside the file path
    so the hash can never disagree with what was actually uploaded."""
    entry = await db.get(BudgetEntry, entry_id)
    if entry is None:
        return Err(BudgetError.NotFound)

    file_hash = hashlib.sha256(file_bytes).hexdigest()
    evidence_id = uuid4()
    db.add(
        BudgetEntryEvidence(
            id=evidence_id,
            budget_entry_id=entry_id,
            file_path=file_path,
            file_hash=file_hash,
        )
    )
    await db.flush()
    return Ok(evidence_id)


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
    """
    original = await db.get(BudgetEntry, entry_id)
    if original is None:
        return Err(BudgetError.NotFound)

    has_evidence = await _entry_has_evidence(db, entry_id)
    if has_evidence is None:
        return Err(BudgetError.NotFound)

    if not has_evidence:
        if amount is not None:
            original.amount = amount
        if category is not None:
            original.category = category
        if occurred_on is not None:
            original.occurred_on = occurred_on
        if vendor is not None:
            original.vendor = vendor
        await db.flush()
        return Ok(entry_id)

    # NOTE: this branch is the actual invariant -- do not "simplify" it back
    # to an UPDATE later just because it looks like duplicate work with the
    # no-evidence branch above. The whole point is that these two paths must
    # never converge.
    original.deleted_at = datetime.now(timezone.utc)
    new_id = uuid4()
    db.add(
        BudgetEntry(
            id=new_id,
            amount=amount if amount is not None else original.amount,
            category=category if category is not None else original.category,
            occurred_on=occurred_on
            if occurred_on is not None
            else original.occurred_on,
            vendor=vendor if vendor is not None else original.vendor,
            memo=original.memo,
            corrects_entry_id=entry_id,
        )
    )
    await db.flush()
    return Ok(new_id)


async def _entry_has_evidence(db: AsyncSession, entry_id: UUID) -> bool | None:
    """Returns None if entry_id doesn't exist, else whether it has >=1
    evidence row attached. Split out so correct_entry's branch logic above
    is testable independent of the not-yet-implemented write paths."""
    entry = await db.get(BudgetEntry, entry_id)
    if entry is None:
        return None
    count = (
        await db.execute(
            select(func.count())
            .select_from(BudgetEntryEvidence)
            .where(BudgetEntryEvidence.budget_entry_id == entry_id)
        )
    ).scalar_one()
    return count > 0
