from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, time, timedelta, timezone

from logand_backend.app.config import AppConfig
from logand_backend.db import base as db_base
from logand_backend.domain.invoices.refunds import reconcile_pending_paypal_refunds
from logand_backend.domain.invoices.service import reconcile_pending_paypal_captures
from logand_backend.logging.logger import get_logger, log_dir
from logand_backend.logging.retention import prune_logs
from logand_backend.scripts.generate_recurring_invoices import run

log = get_logger(__name__)

# Runs once daily at this UTC hour -- matches ops/backup.Dockerfile's own
# nightly-cron convention (that one fires at 03:00 via dcron; this fires
# an hour later so it never overlaps a backup mid-dump, though the two
# don't actually touch the same tables/files at all).
_RUN_HOUR_UTC = 4


def seconds_until_next_run(now: datetime, run_hour_utc: int = _RUN_HOUR_UTC) -> float:
    """Pure function (no real clock read) so this is directly unit-
    testable -- the actual sleep loop below is a thin, untested-by-
    design wrapper around it, same "keep the real logic out of the
    entrypoint" convention as generate_recurring_invoices.py's own doc
    comment.
    """
    target = datetime.combine(now.date(), time(run_hour_utc, 0), tzinfo=timezone.utc)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def main_loop() -> None:
    """No system cron/dcron here -- this Dockerfile's final stage runs as
    a non-root `appuser` (see backend/Dockerfile), and cron's daemon
    needs root to manage per-user crontabs. A plain sleep-until-next-run
    loop needs no OS package and no elevated user at all, at the cost of
    only running jobs on one fixed shared schedule (fine -- every job
    below is daily housekeeping with no reason to run on its own cadence;
    see reconcile_pending_paypal_refunds' own doc comment for why it
    rides along here rather than getting a dedicated service)."""
    while True:
        delay = seconds_until_next_run(datetime.now(timezone.utc))
        log.info("next scheduled run in %.0f seconds", delay)
        await asyncio.sleep(delay)
        try:
            created = await run()
            log.info(
                "recurring-invoice run complete: %d draft(s) created", len(created)
            )
        except Exception:
            # Log and keep looping -- one failed run (a transient DB
            # blip, say) must not kill the whole long-running container;
            # it'll just try again at tomorrow's scheduled time.
            log.exception("recurring-invoice run failed")

        # Independent DB session from run()'s own (that one opens and
        # disposes its own engine per-call, same as this) -- polls any
        # PayPal refund still "pending" for real settlement (see M1 in
        # FINDINGS.md history: PayPal delivers no webhook this app
        # subscribes to for refund completion, unlike Stripe).
        try:
            cfg = AppConfig.from_external(argparse.Namespace())
            db_base.init_engine(cfg.database_url)
            session = db_base.get_session()
            try:
                settled = await reconcile_pending_paypal_refunds(session, cfg)
                if settled:
                    log.info(
                        "paypal refund reconciliation: settled %d refund(s)", settled
                    )
            finally:
                await session.close()
                await db_base.dispose_engine()
        except Exception:
            log.exception("paypal refund reconciliation run failed")

        # Independent DB session, same pattern as the refund reconciler
        # just above -- polls any PayPal capture still "pending" for
        # real settlement (see M1 in FINDINGS.md: PayPal delivers no
        # webhook this app subscribes to for capture completion either).
        try:
            cfg = AppConfig.from_external(argparse.Namespace())
            db_base.init_engine(cfg.database_url)
            session = db_base.get_session()
            try:
                settled = await reconcile_pending_paypal_captures(session, cfg)
                if settled:
                    log.info(
                        "paypal capture reconciliation: settled %d payment(s)",
                        settled,
                    )
            finally:
                await session.close()
                await db_base.dispose_engine()
        except Exception:
            log.exception("paypal capture reconciliation run failed")

        # Same daily cadence as the recurring-invoice job above -- log
        # rotation/pruning needs to run somewhere on a schedule, and this
        # container already has the one always-on daily loop, so it just
        # rides along rather than needing its own separate service.
        try:
            deleted = prune_logs(log_dir())
            if deleted:
                log.info("log retention: pruned %d old log file(s)", len(deleted))
        except Exception:
            log.exception("log retention run failed")


if __name__ == "__main__":
    asyncio.run(main_loop())
