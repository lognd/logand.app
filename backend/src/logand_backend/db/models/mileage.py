from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from logand_backend.db.base import Base


class MileageEntry(Base):
    __tablename__ = "mileage_entries"
    __table_args__ = (
        # Belt-and-suspenders with domain/mileage/service.py's own
        # validation -- distance must always be non-negative regardless of
        # whether it arrived as a raw value or was derived from
        # start/end odometer readings.
        CheckConstraint("distance >= 0", name="ck_mileage_entries_distance_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    vehicle: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Minimal-input-friendly (see domain/mileage/service.py): a caller can
    # supply either a raw `distance` (the common phone-app case -- "12.4
    # miles, done") or start_odometer/end_odometer (the common
    # dashboard-photo case), never both required. Whichever wasn't
    # supplied directly is left None here -- `distance` is always the
    # authoritative, always-populated field every reader should use.
    start_odometer: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 1), nullable=True
    )
    end_odometer: Mapped[Decimal | None] = mapped_column(Numeric(10, 1), nullable=True)
    distance: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True by default -- the common case for a tracked trip is the
    # deductible/business one; a caller logs personal mileage only when
    # they specifically want it recorded (e.g. to net out total odometer
    # use), not as the default assumption.
    business: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
