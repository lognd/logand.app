from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.db.models.budget import BudgetEntry
from logand_backend.db.models.receipts import Receipt
from logand_backend.errors import ReceiptError


async def create_receipt(
    db: AsyncSession,
    file_bytes: bytes,
    file_path: str,
    *,
    vendor: str | None = None,
    amount: Decimal | None = None,
    category: str | None = None,
    occurred_on: date | None = None,
    note: str | None = None,
) -> UUID:
    """No error return -- capturing a receipt has no failure mode besides
    the file upload itself (handled by the API layer/storage backend
    before this is even called). Same hash-computed-server-side pattern
    as domain/budget/service.py::attach_evidence, so the recorded hash
    can never disagree with what was actually uploaded.
    """
    receipt_id = uuid4()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    db.add(
        Receipt(
            id=receipt_id,
            file_path=file_path,
            file_hash=file_hash,
            vendor=vendor,
            amount=amount,
            category=category,
            occurred_on=occurred_on,
            note=note,
        )
    )
    await db.flush()
    return receipt_id


async def reconcile_receipt(
    db: AsyncSession, receipt_id: UUID, budget_entry_id: UUID
) -> Result[None, ReceiptError]:
    receipt = await db.get(Receipt, receipt_id)
    if receipt is None or receipt.deleted_at is not None:
        return Err(ReceiptError.NotFound)
    entry = await db.get(BudgetEntry, budget_entry_id)
    if entry is None or entry.deleted_at is not None:
        return Err(ReceiptError.BudgetEntryNotFound)

    receipt.reconciled_budget_entry_id = budget_entry_id
    await db.flush()
    return Ok(None)


async def delete_receipt(
    db: AsyncSession, receipt_id: UUID
) -> Result[None, ReceiptError]:
    receipt = await db.get(Receipt, receipt_id)
    if receipt is None or receipt.deleted_at is not None:
        return Err(ReceiptError.NotFound)
    receipt.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return Ok(None)


async def list_receipts(
    db: AsyncSession,
    *,
    reconciled: bool | None = None,
    category: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[Receipt]:
    query = select(Receipt).where(Receipt.deleted_at.is_(None))
    if reconciled is not None:
        if reconciled:
            query = query.where(Receipt.reconciled_budget_entry_id.is_not(None))
        else:
            query = query.where(Receipt.reconciled_budget_entry_id.is_(None))
    if category is not None:
        query = query.where(Receipt.category == category)
    if date_from is not None:
        query = query.where(Receipt.occurred_on >= date_from)
    if date_to is not None:
        query = query.where(Receipt.occurred_on <= date_to)
    rows = (
        (await db.execute(query.order_by(Receipt.captured_at.desc()))).scalars().all()
    )
    return list(rows)


async def get_receipt(
    db: AsyncSession, receipt_id: UUID
) -> Result[Receipt, ReceiptError]:
    receipt = await db.get(Receipt, receipt_id)
    if receipt is None or receipt.deleted_at is not None:
        return Err(ReceiptError.NotFound)
    return Ok(receipt)
