from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from logand_backend.db.models.budget import BudgetEntry
from logand_backend.domain.budget.service import (
    attach_evidence,
    correct_entry,
    create_entry,
)
from logand_backend.errors import BudgetError


async def test_create_entry(db_session) -> None:
    result = await create_entry(
        db_session, Decimal("42.50"), "supplies", date(2026, 1, 1), vendor="Acme"
    )
    assert result.is_ok
    entry = await db_session.get(BudgetEntry, result.danger_ok)
    assert entry.amount == Decimal("42.50")
    assert entry.category == "supplies"


async def test_attach_evidence_computes_correct_sha256(db_session) -> None:
    entry_id = (
        await create_entry(db_session, Decimal("10.00"), "travel", date(2026, 1, 1))
    ).danger_ok
    file_bytes = b"this is a fake receipt pdf"

    result = await attach_evidence(db_session, entry_id, file_bytes, file_path="x.pdf")

    assert result.is_ok
    from logand_backend.db.models.budget import BudgetEntryEvidence

    evidence = await db_session.get(BudgetEntryEvidence, result.danger_ok)
    assert evidence.file_hash == hashlib.sha256(file_bytes).hexdigest()


async def test_attach_evidence_not_found(db_session) -> None:
    result = await attach_evidence(db_session, uuid4(), b"x", file_path="x.pdf")
    assert result.is_err
    assert result.danger_err == BudgetError.NotFound


async def test_correct_entry_without_evidence_mutates_in_place(db_session) -> None:
    entry_id = (
        await create_entry(db_session, Decimal("10.00"), "travel", date(2026, 1, 1))
    ).danger_ok

    result = await correct_entry(db_session, entry_id, amount=Decimal("15.00"))

    assert result.is_ok
    assert result.danger_ok == entry_id  # same row, mutated in place
    entry = await db_session.get(BudgetEntry, entry_id)
    assert entry.amount == Decimal("15.00")
    assert entry.deleted_at is None


async def test_correct_entry_with_evidence_never_mutates_original(db_session) -> None:
    """The core invariant from docs/design/05: once evidence is attached, a
    correction must soft-delete the original and insert a new row pointing
    back to it -- never overwrite the original in place."""
    entry_id = (
        await create_entry(db_session, Decimal("100.00"), "supplies", date(2026, 1, 1))
    ).danger_ok
    await attach_evidence(db_session, entry_id, b"receipt bytes", file_path="r.pdf")

    result = await correct_entry(db_session, entry_id, amount=Decimal("90.00"))

    assert result.is_ok
    new_id = result.danger_ok
    assert new_id != entry_id

    # Original row still exists, untouched amount, but soft-deleted.
    original = await db_session.get(BudgetEntry, entry_id)
    assert original is not None
    assert original.amount == Decimal("100.00")
    assert original.deleted_at is not None

    # New row carries the correction and points back at the original.
    correction = await db_session.get(BudgetEntry, new_id)
    assert correction.amount == Decimal("90.00")
    assert correction.corrects_entry_id == entry_id

    # A query for "active" (non-deleted) entries excludes the original.
    active_ids = (
        (
            await db_session.execute(
                select(BudgetEntry.id).where(BudgetEntry.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    assert entry_id not in active_ids
    assert new_id in active_ids


async def test_correct_entry_with_evidence_carries_forward_unspecified_fields(
    db_session,
) -> None:
    entry_id = (
        await create_entry(
            db_session, Decimal("100.00"), "supplies", date(2026, 1, 1), vendor="Acme"
        )
    ).danger_ok
    await attach_evidence(db_session, entry_id, b"receipt", file_path="r.pdf")

    # Only correct the amount; category/vendor should carry forward.
    new_id = (
        await correct_entry(db_session, entry_id, amount=Decimal("80.00"))
    ).danger_ok

    correction = await db_session.get(BudgetEntry, new_id)
    assert correction.category == "supplies"
    assert correction.vendor == "Acme"


async def test_correct_entry_not_found(db_session) -> None:
    result = await correct_entry(db_session, uuid4(), amount=Decimal("1.00"))
    assert result.is_err
    assert result.danger_err == BudgetError.NotFound
