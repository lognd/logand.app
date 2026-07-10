from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from logand_backend.app.config import AppConfig
from logand_backend.domain.invoices.tax import stripe_reconcile


async def test_reconcile_stripe_tax_unconfigured_returns_zeros_without_calling_stripe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = AppConfig(payment_processor_secret=None, stripe_publishable_key=None)

    async def _boom(*args, **kwargs):
        raise AssertionError("must not call Stripe when unconfigured")

    monkeypatch.setattr(stripe_reconcile, "_create_and_poll_report", _boom)

    summary = await stripe_reconcile.reconcile_stripe_tax(
        cfg, date(2026, 1, 1), date(2026, 1, 31)
    )
    assert summary.total_tax_collected == Decimal(0)
    assert summary.by_jurisdiction == {}
    assert summary.transaction_count == 0


async def test_reconcile_stripe_tax_sums_fake_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = AppConfig(
        payment_processor_secret="sk_test_fake", stripe_publishable_key="pk_test_fake"
    )

    fake_run = SimpleNamespace(
        id="run_1", status="succeeded", result=SimpleNamespace(id="file_1")
    )

    async def fake_create_and_poll(_cfg, _from, _to):
        return fake_run

    fake_csv = "jurisdiction,tax_amount\nUS-TN,700\nUS-customs,200\nUS-TN,300\n"

    async def fake_download(_cfg, file_id):
        assert file_id == "file_1"
        return fake_csv

    monkeypatch.setattr(
        stripe_reconcile, "_create_and_poll_report", fake_create_and_poll
    )
    monkeypatch.setattr(stripe_reconcile, "_download_report_csv", fake_download)

    summary = await stripe_reconcile.reconcile_stripe_tax(
        cfg, date(2026, 1, 1), date(2026, 1, 31)
    )
    assert summary.total_tax_collected == Decimal(12)
    assert summary.by_jurisdiction == {"US-TN": Decimal(10), "US-customs": Decimal(2)}
    assert summary.transaction_count == 3


async def test_reconcile_stripe_tax_returns_zeros_when_report_never_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = AppConfig(
        payment_processor_secret="sk_test_fake", stripe_publishable_key="pk_test_fake"
    )

    async def fake_create_and_poll(_cfg, _from, _to):
        return None

    async def _boom(*args, **kwargs):
        raise AssertionError("must not attempt a download with no completed run")

    monkeypatch.setattr(
        stripe_reconcile, "_create_and_poll_report", fake_create_and_poll
    )
    monkeypatch.setattr(stripe_reconcile, "_download_report_csv", _boom)

    summary = await stripe_reconcile.reconcile_stripe_tax(
        cfg, date(2026, 1, 1), date(2026, 1, 31)
    )
    assert summary.total_tax_collected == Decimal(0)
