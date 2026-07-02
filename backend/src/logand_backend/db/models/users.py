from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role in ('admin', 'customer')", name="ck_users_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # CAN-SPAM opt-out flag -- set True via the no-auth unsubscribe link
    # (api/notifications.py) in every email's footer. Checked by
    # domain/notifications/mailer.py before every send; never bypassed for
    # "important" mail (there is no such exemption in this app -- invoice
    # notifications are exactly the kind of transactional-but-still-email
    # mail CAN-SPAM's opt-out right applies to).
    emails_opted_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # None = active (the default for every existing/new account). Set to
    # a real timestamp to deactivate -- checked at login (see
    # domain/auth/service.py::login) so a disabled account genuinely
    # can't authenticate, not just "hidden" from some admin list while
    # still able to log in. Deliberately a nullable timestamp, not a
    # plain boolean -- "when was this disabled" is itself useful audit
    # information a bare is_active flag would throw away.
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
