from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.db.models.tax import ItemTaxClassification

# The "do-as-we-go" per-item classification cache (docs/design/16-sales-tax.md
# Phase 5). Every item is classified once and reused; a human confirms or
# overrides. The invariant enforced here: a human decision (confirmed /
# overridden) is NEVER silently overwritten by a later Claude result.

_WS = re.compile(r"\s+")


def normalize_key(description: str) -> str:
    """The cache key for an item -- lowercased, whitespace-collapsed. Two
    invoice lines that describe the same thing map to the same key, so the
    item is classified once. Deliberately simple/deterministic (not fuzzy):
    a near-miss just creates a new pending row for review, which is the
    correct 'go look it up' behavior."""
    return _WS.sub(" ", description.strip().lower())


async def get(db: AsyncSession, key: str) -> ItemTaxClassification | None:
    return (
        await db.execute(
            select(ItemTaxClassification).where(
                ItemTaxClassification.normalized_key == key
            )
        )
    ).scalar_one_or_none()


async def get_many(
    db: AsyncSession, keys: list[str]
) -> dict[str, ItemTaxClassification]:
    """Batched lookup for all keys at once (one query, no N+1)."""
    if not keys:
        return {}
    rows = (
        (
            await db.execute(
                select(ItemTaxClassification).where(
                    ItemTaxClassification.normalized_key.in_(keys)
                )
            )
        )
        .scalars()
        .all()
    )
    return {r.normalized_key: r for r in rows}


async def upsert_pending(
    db: AsyncSession,
    *,
    key: str,
    description: str,
    category: str,
    taxable: bool,
    hts_code: str | None,
    model: str | None,
    rationale: str | None,
) -> ItemTaxClassification:
    """Record a Claude classification as `pending`. If a row already exists
    and a human has confirmed/overridden it, leave it untouched (a human
    decision outranks the model). A prior pending row is refreshed."""
    existing = await get(db, key)
    if existing is not None:
        if existing.status in ("confirmed", "overridden"):
            return existing
        existing.description = description
        existing.category = category
        existing.taxable = taxable
        existing.hts_code = hts_code
        existing.source = "claude"
        existing.model = model
        existing.rationale = rationale
        existing.status = "pending"
        await db.flush()
        return existing
    row = ItemTaxClassification(
        normalized_key=key,
        description=description,
        category=category,
        taxable=taxable,
        hts_code=hts_code,
        status="pending",
        source="claude",
        model=model,
        rationale=rationale,
    )
    db.add(row)
    await db.flush()
    return row


async def confirm(
    db: AsyncSession, key: str, admin_id: UUID
) -> ItemTaxClassification | None:
    """Accept the current (pending) classification as-is -- it becomes
    human-authoritative and is never re-asked."""
    row = await get(db, key)
    if row is None:
        return None
    row.status = "confirmed"
    row.confirmed_by = admin_id
    row.confirmed_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def override(
    db: AsyncSession,
    key: str,
    *,
    category: str,
    taxable: bool,
    hts_code: str | None,
    admin_id: UUID,
) -> ItemTaxClassification:
    """Replace the classification with an explicit human choice. Creates the
    row if the item hasn't been seen yet (an admin pre-classifying an item)."""
    row = await get(db, key)
    now = datetime.now(timezone.utc)
    if row is None:
        row = ItemTaxClassification(
            normalized_key=key,
            description=key,
            category=category,
            taxable=taxable,
            hts_code=hts_code,
            status="overridden",
            source="manual",
            confirmed_by=admin_id,
            confirmed_at=now,
        )
        db.add(row)
    else:
        row.category = category
        row.taxable = taxable
        row.hts_code = hts_code
        row.status = "overridden"
        row.source = "manual"
        row.confirmed_by = admin_id
        row.confirmed_at = now
    await db.flush()
    return row


async def list_by_status(
    db: AsyncSession, status: str | None = None
) -> list[ItemTaxClassification]:
    """For the admin review UI. `status=None` returns all; typically called
    with 'pending' to surface what needs a human decision."""
    stmt = select(ItemTaxClassification).order_by(
        ItemTaxClassification.updated_at.desc()
    )
    if status is not None:
        stmt = stmt.where(ItemTaxClassification.status == status)
    return list((await db.execute(stmt)).scalars().all())
