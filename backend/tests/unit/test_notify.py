from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Invoice
from logand_backend.db.models.users import User
from logand_backend.domain.notifications import notify

# Unit-level (mocked db.get, mocked mailer.send_email), not another
# full HTTP+real-SMTP round trip like tests/system/test_notifications.py --
# these exist specifically to cheaply exercise notify.py's own branches
# (not-configured, opted-out, customer missing, send failure swallowed)
# without needing a real invoice/customer/SMTP server per case.


def _cfg(**overrides: object) -> AppConfig:
    return AppConfig(smtp_host="smtp.example.com", **overrides)  # type: ignore[arg-type]


def _invoice() -> Invoice:
    return Invoice(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        status="sent",
        amount_total=Decimal("10.00"),
        currency="usd",
    )


class _FakeDb:
    def __init__(self, user: User | None) -> None:
        self._user = user

    async def get(self, _model: type, _id: object) -> User | None:
        return self._user


async def test_notify_invoice_sent_noop_when_smtp_not_configured() -> None:
    cfg = AppConfig()  # smtp_host is None by default
    db = _FakeDb(User(id=uuid.uuid4(), email="c@example.com", role="customer"))
    await notify.notify_invoice_sent(db, cfg, _invoice())  # must not raise


async def test_notify_invoice_sent_noop_when_customer_missing() -> None:
    cfg = _cfg()
    db = _FakeDb(None)
    await notify.notify_invoice_sent(db, cfg, _invoice())


async def test_notify_invoice_sent_noop_when_opted_out() -> None:
    cfg = _cfg()
    user = User(
        id=uuid.uuid4(),
        email="c@example.com",
        role="customer",
        emails_opted_out=True,
    )
    db = _FakeDb(user)
    await notify.notify_invoice_sent(db, cfg, _invoice())


async def test_notify_invoice_sent_swallows_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg()
    user = User(id=uuid.uuid4(), email="c@example.com", role="customer")
    db = _FakeDb(user)
    monkeypatch.setattr(
        notify.mailer, "send_email", AsyncMock(side_effect=OSError("boom"))
    )
    await notify.notify_invoice_sent(db, cfg, _invoice())  # must not raise


async def test_notify_payment_received_noop_when_smtp_not_configured() -> None:
    cfg = AppConfig()
    db = _FakeDb(User(id=uuid.uuid4(), email="c@example.com", role="customer"))
    await notify.notify_payment_received(db, cfg, _invoice(), Decimal("10.00"))


async def test_notify_payment_received_noop_when_customer_missing() -> None:
    cfg = _cfg()
    db = _FakeDb(None)
    await notify.notify_payment_received(db, cfg, _invoice(), Decimal("10.00"))


async def test_notify_payment_received_noop_when_opted_out() -> None:
    cfg = _cfg()
    user = User(
        id=uuid.uuid4(),
        email="c@example.com",
        role="customer",
        emails_opted_out=True,
    )
    db = _FakeDb(user)
    await notify.notify_payment_received(db, cfg, _invoice(), Decimal("10.00"))


async def test_notify_payment_received_swallows_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _cfg()
    user = User(id=uuid.uuid4(), email="c@example.com", role="customer")
    db = _FakeDb(user)
    monkeypatch.setattr(
        notify.mailer, "send_email", AsyncMock(side_effect=OSError("boom"))
    )
    await notify.notify_payment_received(db, cfg, _invoice(), Decimal("10.00"))
