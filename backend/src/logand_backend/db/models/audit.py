from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base


class AdminAuditLog(Base):
    """One shared audit trail for every admin action that changes real
    data outside its own domain-specific audit table (InventoryAdjustment
    already covers inventory quantity changes; this covers everything
    else -- user account actions (#80: deactivate/reactivate/password
    reset) and the generic raw-data-browser's row edits (#81)).

    `before_state`/`after_state` are full-row JSON snapshots, not just a
    diff -- this IS the rollback record (per the user's own requirement:
    "rollback-safe design... make sure there is validation so that at no
    point can ANYTHING be in an INVALID/CORRUPT state"). To revert a
    change, re-apply `before_state` through the same validated write path
    that produced it (never a raw UPDATE bypassing constraints) -- see
    domain/admin_data/service.py's revert_change.

    Never stores password hashes or other secrets in a *_state snapshot
    -- see domain/users/service.py's own redaction before writing here.
    """

    __tablename__ = "admin_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable + SET NULL (not RESTRICT) -- an audit log entry must
    # survive the admin account that made it being deleted; "we don't
    # know who anymore" is a real, honest state, not a reason to block
    # deleting an old admin account or to CASCADE-delete history.
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # e.g. "user.deactivate", "user.reactivate", "user.reset_password",
    # "data.update", "data.update.noop" (see admin_data/service.py's
    # update_row -- a no-op edit still gets a distinct, tagged entry
    # rather than an indistinguishable-from-real "data.update"),
    # "data.insert", "data.delete", "data.revert".
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_table: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stringified -- primary keys vary in type across tables (UUID here,
    # could be composite elsewhere), so this stays a plain string
    # representation rather than trying to type this column per-table.
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
