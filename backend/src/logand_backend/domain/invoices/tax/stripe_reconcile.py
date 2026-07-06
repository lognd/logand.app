"""Best-effort reconciliation of tax Stripe already calculated/collected
against our own tax report (docs/design/16-sales-tax.md). Surfaces Stripe
Tax's own numbers for a date range so an admin can compare them against
`domain/invoices/tax/report.py`'s deterministic report for the same
invoices -- it never feeds INTO our own tax math.

## Why the Reporting API, not `stripe.tax.Transaction`

Stripe Tax's `Transaction` object is retrieve-by-id / create-from-
calculation only -- there is no "list every transaction in a date range"
endpoint on it (confirmed against stripe-python 15.3, which exposes no
`list`/`list_async` on `stripe.tax.Transaction`). The one real Stripe
surface that answers "how much tax did Stripe collect between two dates,
broken down by jurisdiction" is the async Reporting API: create a
`stripe.reporting.ReportRun` of type `"tax.transactions.itemized.3"`
scoped to the interval, poll it to completion, then download and parse the
CSV it produces. That's what this module does.

Best-effort throughout: Stripe Tax not being enabled on the account, a
report run that never completes, or any Stripe/network error all return a
zeroed `StripeTaxSummary` with a warning logged, never an exception into
the caller (mirrors `domain/payments/providers/stripe_provider.is_configured`
and PayPal's "gracefully unavailable" convention).
"""

from __future__ import annotations

import asyncio
import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation

from logand_backend.app.config import AppConfig
from logand_backend.domain.payments.providers import stripe_provider
from logand_backend.logging import get_logger

_log = get_logger(__name__)

_REPORT_TYPE = "tax.transactions.itemized.3"
# Report runs are async on Stripe's side -- typically seconds, but not
# instant. Bounded polling so a stuck run can never hang this call forever;
# a run that hasn't finished in this window is reported as unavailable
# (zeros) rather than blocking the caller.
_POLL_MAX_ATTEMPTS = 10
_POLL_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class StripeTaxSummary:
    """Stripe's own view of tax collected over a date range. `by_jurisdiction`
    keys are Stripe's jurisdiction labels (e.g. "US-TN") as reported in the
    itemized CSV; empty/zeroed when Stripe Tax has nothing to report or
    isn't configured."""

    total_tax_collected: Decimal
    by_jurisdiction: dict[str, Decimal] = field(default_factory=dict)
    transaction_count: int = 0


def _zero() -> StripeTaxSummary:
    return StripeTaxSummary(total_tax_collected=Decimal(0))


def _to_unix(d: date) -> int:
    return int(datetime.combine(d, time.min, tzinfo=timezone.utc).timestamp())


async def _create_and_poll_report(
    cfg: AppConfig, from_date: date, to_date: date
) -> object | None:
    """Creates the itemized tax-transactions report run and polls it to a
    terminal state. Returns the completed ReportRun, or None if it never
    reached "succeeded" within the poll budget or Stripe/network raised."""
    import stripe

    stripe.api_key = cfg.payment_processor_secret
    try:
        run = await stripe.reporting.ReportRun.create_async(
            report_type=_REPORT_TYPE,
            parameters={
                "interval_start": _to_unix(from_date),
                "interval_end": _to_unix(to_date),
            },
        )
        for _ in range(_POLL_MAX_ATTEMPTS):
            if run.status == "succeeded":
                return run
            if run.status == "failed":
                _log.warning(
                    "stripe tax reconcile: report run failed",
                    extra={"report_run_id": run.id},
                )
                return None
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            run = await stripe.reporting.ReportRun.retrieve_async(run.id)
        _log.warning(
            "stripe tax reconcile: report run did not complete in time",
            extra={"report_run_id": run.id},
        )
        return None
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise out
        _log.warning(
            "stripe tax reconcile: Stripe reporting call failed",
            extra={"error": str(exc)},
        )
        return None


async def _download_report_csv(cfg: AppConfig, file_id: str) -> str | None:
    """Downloads the completed report's CSV body via Stripe's file API.
    Isolated as its own function so tests can monkeypatch just the network
    hop without faking a full ReportRun lifecycle."""
    import httpx
    import stripe

    stripe.api_key = cfg.payment_processor_secret
    try:
        file_obj = await stripe.File.retrieve_async(file_id)
        url = getattr(file_obj, "url", None)
        if not url:
            return None
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {cfg.payment_processor_secret}"}
            )
            resp.raise_for_status()
            return resp.text
    except Exception as exc:  # noqa: BLE001 -- best-effort, never raise out
        _log.warning(
            "stripe tax reconcile: report file download failed",
            extra={"file_id": file_id, "error": str(exc)},
        )
        return None


def _parse_report_csv(csv_text: str) -> StripeTaxSummary:
    """Sums the itemized report's tax_amount column, grouped by
    jurisdiction. Tolerant of missing/blank cells (skipped, not fatal) --
    this is a reporting aid, not money math that feeds our own totals."""
    reader = csv.DictReader(io.StringIO(csv_text))
    total = Decimal(0)
    by_jurisdiction: dict[str, Decimal] = {}
    count = 0
    for row in reader:
        raw_amount = (row.get("tax_amount") or row.get("amount_tax") or "").strip()
        if not raw_amount:
            continue
        try:
            # Stripe reports amounts in the currency's smallest unit
            # (cents for USD) -- same convention as every other Stripe
            # amount this app already handles elsewhere.
            amount = Decimal(raw_amount) / Decimal(100)
        except InvalidOperation:
            continue
        jurisdiction = (
            row.get("jurisdiction") or row.get("tax_jurisdiction") or "unknown"
        ).strip() or "unknown"
        total += amount
        by_jurisdiction[jurisdiction] = (
            by_jurisdiction.get(jurisdiction, Decimal(0)) + amount
        )
        count += 1
    return StripeTaxSummary(
        total_tax_collected=total,
        by_jurisdiction=by_jurisdiction,
        transaction_count=count,
    )


async def reconcile_stripe_tax(
    cfg: AppConfig, from_date: date, to_date: date
) -> StripeTaxSummary:
    """Stripe's own tax-collected summary for [from_date, to_date] --
    for an admin to compare against `tax.report.build_tax_report`'s
    deterministic figures for the same period. Returns all-zeros (never
    raises) when Stripe isn't configured, Stripe Tax has nothing to
    report, or anything about the report-run round trip fails.
    """
    if not stripe_provider.is_configured(cfg):
        _log.info("stripe tax reconcile: Stripe not configured, returning zeros")
        return _zero()

    run = await _create_and_poll_report(cfg, from_date, to_date)
    if run is None:
        return _zero()

    run_result = getattr(run, "result", None)
    file_id = getattr(run_result, "id", None) if run_result else None
    if not file_id:
        _log.warning(
            "stripe tax reconcile: report succeeded with no result file",
            extra={"report_run_id": getattr(run, "id", None)},
        )
        return _zero()

    csv_text = await _download_report_csv(cfg, file_id)
    if csv_text is None:
        return _zero()

    return _parse_report_csv(csv_text)
