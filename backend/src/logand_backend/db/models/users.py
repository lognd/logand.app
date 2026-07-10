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
        # docs/design/16: a row with email_verified_at set MUST have a
        # password_hash -- a verified row with no password would be a
        # login-bypass shaped hole (nothing to verify_password against,
        # yet "verified"). Declared on the model (not just the migration)
        # because tests/conftest.py's db_engine fixture builds schema via
        # Base.metadata.create_all(), which never runs Alembic at all.
        CheckConstraint(
            "email_verified_at is null or password_hash is not null",
            name="ck_users_contact_or_active",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # NULL means this row is a "contact" -- addressable (invoices can FK to
    # it, mail can go to it) but not an account: nothing can authenticate
    # as it (see domain/auth/service.py::login's explicit None check, run
    # through verify_password against DUMMY_PASSWORD_HASH so the timing
    # doesn't fork). Set once someone registers against this email (see
    # domain/auth/service.py::register) or claims it via a 'claim' token
    # (domain/auth/email_verification.py). See docs/design/16 for the full
    # contact/unverified/active state table.
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # None until the inbox is proven (a 'verify' or 'claim' token
    # redeemed) -- gates BOTH login (domain/auth/service.py::login) and
    # every customer-facing invoice read path (docs/design/16's "load-
    # bearing invariant": visibility is gated on this column, never on
    # mere linkage). Deliberately a timestamp, not a bool, for the same
    # audit-trail reason as disabled_at above.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
