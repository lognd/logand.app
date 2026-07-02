from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone

from logand_backend.logging.logger import get_logger
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
    only running one job on one fixed schedule (fine -- this container's
    only job, ever, is this one)."""
    while True:
        delay = seconds_until_next_run(datetime.now(timezone.utc))
        log.info("next recurring-invoice run in %.0f seconds", delay)
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


if __name__ == "__main__":
    asyncio.run(main_loop())
