from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typani.result import Ok

from logand_backend.app.config import AppConfig
from logand_backend.db.models.invoices import Invoice, InvoiceLineItem
from logand_backend.db.models.users import User
from logand_backend.domain.notifications import notify

# Unit-level (mocked db.get/execute, mocked mailer.send_email and
# generate_invoice_pdf), not another full HTTP+real-SMTP+real-latexmk
# round trip like tests/system/test_notifications.py -- these exist
# specifically to cheaply exercise notify.py's own branches (not-
# configured, opted-out, customer/invoice missing, send failure
# swallowed, PDF-generation failure swallowed, attachment ordering)
# without needing a real invoice/customer/SMTP server/LaTeX toolchain
# per case.


def _cfg(**overrides: object) -> AppConfig:
    return AppConfig(smtp_host="smtp.example.com", **overrides)  # type: ignore[arg-type]


def _invoice(**overrides: object) -> Invoice:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        status="sent",
        amount_total=Decimal("10.00"),
        currency="usd",
        due_date=None,
        memo=None,
        deleted_at=None,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Invoice(**defaults)  # type: ignore[arg-type]


class _FakeScalars:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def all(self) -> list[object]:
        return self._items


class _FakeResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._items)


class _FakeDb:
    """Routes db.get() by model type (Invoice vs. User) instead of
    blindly returning one fixed object -- notify_invoice_sent now loads
    both the invoice (via export.load_invoice_export_data) and the
    customer, whereas before it only ever loaded the customer."""

    def __init__(
        self,
        user: User | None,
        invoice: Invoice | None = None,
        line_items: list[InvoiceLineItem] | None = None,
    ) -> None:
        self._user = user
        self._invoice = invoice
        self._line_items = line_items or []

    async def get(self, model: type, _id: object) -> object:
        if model is User:
            return self._user
        if model is Invoice:
            return self._invoice
        raise AssertionError(f"unexpected model {model!r} passed to db.get")

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult(self._line_items)


async def test_notify_invoice_sent_noop_when_smtp_not_configured() -> None:
    cfg = AppConfig()  # smtp_host is None by default
    db = _FakeDb(
        User(
            id=uuid.uuid4(),
            email="c@example.com",
            password_hash="hashed",
            role="customer",
        )
    )
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
    user = User(
        id=uuid.uuid4(), email="c@example.com", password_hash="hashed", role="customer"
    )
    invoice = _invoice()
    db = _FakeDb(user, invoice=invoice)
    monkeypatch.setattr(
        notify, "generate_invoice_pdf", AsyncMock(return_value=Ok(b"%PDF-fake"))
    )
    monkeypatch.setattr(
        notify.mailer, "send_email", AsyncMock(side_effect=OSError("boom"))
    )
    await notify.notify_invoice_sent(db, cfg, invoice)  # must not raise


async def test_notify_invoice_sent_logs_the_actual_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression test: a bare `except Exception: _log.error(...)` with no
    exc_info discarded the real error (e.g. an SMTPAuthenticationError's
    "Username and Password not accepted") -- the log said only "failed to
    send," making the actual cause undiagnosable from logs alone. This
    found a real production SMTP auth failure that couldn't otherwise be
    root-caused without SSHing in and reproducing it by hand.
    """
    cfg = _cfg()
    user = User(
        id=uuid.uuid4(), email="c@example.com", password_hash="hashed", role="customer"
    )
    invoice = _invoice()
    db = _FakeDb(user, invoice=invoice)
    monkeypatch.setattr(
        notify, "generate_invoice_pdf", AsyncMock(return_value=Ok(b"%PDF-fake"))
    )
    monkeypatch.setattr(
        notify.mailer,
        "send_email",
        AsyncMock(side_effect=OSError("535 authentication failed")),
    )
    with caplog.at_level("ERROR", logger="logand_backend.domain.notifications.notify"):
        await notify.notify_invoice_sent(db, cfg, invoice)

    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is not None
    assert "535 authentication failed" in str(caplog.records[0].exc_info[1])


async def test_notify_invoice_sent_noop_when_invoice_missing() -> None:
    """Invoice vanished (soft-deleted) between the caller's commit and
    notify_invoice_sent running -- must no-op, not raise."""
    cfg = _cfg()
    user = User(
        id=uuid.uuid4(), email="c@example.com", password_hash="hashed", role="customer"
    )
    db = _FakeDb(user, invoice=None)
    await notify.notify_invoice_sent(db, cfg, _invoice())


async def test_notify_invoice_sent_attaches_pdf_text_and_json_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user's explicit ordering request: PDF, then plaintext, then
    for-robots.json LAST, so a human skimming attachments sees the
    human-readable copies before the machine-readable one."""
    cfg = _cfg()
    user = User(
        id=uuid.uuid4(), email="c@example.com", password_hash="hashed", role="customer"
    )
    invoice = _invoice()
    line_item = InvoiceLineItem(
        id=uuid.uuid4(),
        invoice_id=invoice.id,
        description="Consulting",
        quantity=Decimal("2"),
        unit=None,
        unit_price=Decimal("5.00"),
    )
    db = _FakeDb(user, invoice=invoice, line_items=[line_item])
    monkeypatch.setattr(
        notify, "generate_invoice_pdf", AsyncMock(return_value=Ok(b"%PDF-fake"))
    )
    send_email = AsyncMock()
    monkeypatch.setattr(notify.mailer, "send_email", send_email)

    await notify.notify_invoice_sent(db, cfg, invoice)

    send_email.assert_awaited_once()
    attachments = send_email.await_args.kwargs["attachments"]
    assert [a.filename for a in attachments] == [
        f"invoice-{invoice.id}.pdf",
        f"invoice-{invoice.id}.txt",
        "for-robots.json",
    ]
    assert attachments[-1].filename == "for-robots.json"
    assert attachments[0].content == b"%PDF-fake"
    assert attachments[0].maintype == "application"
    assert attachments[0].subtype == "pdf"
    assert attachments[1].maintype == "text"
    assert attachments[1].subtype == "plain"
    assert attachments[2].maintype == "application"
    assert attachments[2].subtype == "json"

    payload = json.loads(attachments[2].content)
    assert payload["invoice_id"] == str(invoice.id)
    assert payload["line_items"][0]["description"] == "Consulting"
    assert payload["line_items"][0]["line_total"] == "10.00"


async def test_notify_invoice_sent_skips_pdf_attachment_on_render_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort: a LaTeX/PdfRenderError failure must not sink the whole
    notification -- the txt and for-robots.json attachments still go out."""
    cfg = _cfg()
    user = User(
        id=uuid.uuid4(), email="c@example.com", password_hash="hashed", role="customer"
    )
    invoice = _invoice()
    db = _FakeDb(user, invoice=invoice)
    monkeypatch.setattr(
        notify,
        "generate_invoice_pdf",
        AsyncMock(side_effect=notify.PdfRenderError("latexmk failed", log="boom")),
    )
    send_email = AsyncMock()
    monkeypatch.setattr(notify.mailer, "send_email", send_email)

    await notify.notify_invoice_sent(db, cfg, invoice)  # must not raise

    send_email.assert_awaited_once()
    attachments = send_email.await_args.kwargs["attachments"]
    assert [a.filename for a in attachments] == [
        f"invoice-{invoice.id}.txt",
        "for-robots.json",
    ]


async def test_notify_invoice_sent_skips_pdf_attachment_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for a real bug caught while wiring this up: an
    unexpected exception from generate_invoice_pdf (e.g. FileNotFoundError
    when latexmk itself isn't on PATH, not a PdfRenderError) was only
    caught by a narrow `except PdfRenderError`, so it propagated out of
    notify_invoice_sent uncaught and 500'd the whole /send route --
    turning a best-effort attachment into a hard failure of sending the
    invoice at all. Must be swallowed exactly like PdfRenderError is."""
    cfg = _cfg()
    user = User(
        id=uuid.uuid4(), email="c@example.com", password_hash="hashed", role="customer"
    )
    invoice = _invoice()
    db = _FakeDb(user, invoice=invoice)
    monkeypatch.setattr(
        notify,
        "generate_invoice_pdf",
        AsyncMock(side_effect=FileNotFoundError("latexmk")),
    )
    send_email = AsyncMock()
    monkeypatch.setattr(notify.mailer, "send_email", send_email)

    await notify.notify_invoice_sent(db, cfg, invoice)  # must not raise

    send_email.assert_awaited_once()
    attachments = send_email.await_args.kwargs["attachments"]
    assert [a.filename for a in attachments] == [
        f"invoice-{invoice.id}.txt",
        "for-robots.json",
    ]


async def test_notify_payment_received_noop_when_smtp_not_configured() -> None:
    cfg = AppConfig()
    db = _FakeDb(
        User(
            id=uuid.uuid4(),
            email="c@example.com",
            password_hash="hashed",
            role="customer",
        )
    )
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
    user = User(
        id=uuid.uuid4(), email="c@example.com", password_hash="hashed", role="customer"
    )
    db = _FakeDb(user)
    monkeypatch.setattr(
        notify.mailer, "send_email", AsyncMock(side_effect=OSError("boom"))
    )
    await notify.notify_payment_received(db, cfg, _invoice(), Decimal("10.00"))
