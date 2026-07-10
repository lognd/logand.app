from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base


class EmailVerificationToken(Base):
    """One table, one code path, two `purpose` values -- mirrors
    db/models/password_reset_tokens.py's shape verbatim (see docs/design/16).

    'verify' -- minted by domain/auth/service.py::register. Redeeming just
    sets User.email_verified_at.

    'claim' -- minted by domain/notifications/notify.py::notify_invoice_sent
    when the recipient is a contact row (password_hash IS NULL). Redeeming
    takes a password and sets BOTH password_hash and email_verified_at in
    one transaction: clicking the link *is* the proof of inbox control.
    """

    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose in ('verify', 'claim')",
            name="ck_email_verification_tokens_purpose",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # sha256(raw_token), never the raw token itself -- see auth/tokens.py's
    # shared hash_token, same discipline as PasswordResetToken.token_hash.
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # None until redeemed -- single-use, same reasoning as
    # PasswordResetToken.used_at.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
