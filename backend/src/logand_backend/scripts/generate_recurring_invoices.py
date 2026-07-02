from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.app.config import AppConfig
from logand_backend.db import base as db_base
from logand_backend.domain.invoices.recurrence import generate_due_recurring_invoices
from logand_backend.logging.logger import get_logger

log = get_logger(__name__)

# A thin, standalone entrypoint around the real domain function -- see
# docs/design/04-invoices.md's "Recurring invoices" section:
# generate_due_recurring_invoices itself is the tested, cron-agnostic
# logic; this script is just "connect to the real DB, call it, commit,
# log what happened" so it's runnable both from a real scheduled
# container (see ops/scheduler.Dockerfile) and by hand
# (`python -m logand_backend.scripts.generate_recurring_invoices`) for a
# manual catch-up run.


async def run(
    session: AsyncSession | None = None, as_of: date | None = None
) -> list[str]:
    """`session=None` (the real CLI path via main()) connects to
    AppConfig's real database_url and manages the engine's lifecycle
    itself. Passing an already-open `session` (what tests do, reusing the
    same testcontainer-backed engine tests/conftest.py already set up via
    db_base.init_engine) skips all of that -- this function's own logic
    (call the domain function, commit, collect the ids) is what's under
    test, not engine setup that's already covered by
    tests/integration/test_invoices_service.py's direct calls to
    generate_due_recurring_invoices itself.
    """
    owns_session = session is None
    if session is None:
        cfg = AppConfig.from_external(argparse.Namespace())
        db_base.init_engine(cfg.database_url)
        session = db_base.get_session()

    try:
        created = await generate_due_recurring_invoices(
            session, as_of=as_of or date.today()
        )
        await session.commit()
        return [str(invoice_id) for invoice_id in created]
    finally:
        # Only close/dispose what THIS call opened -- a session/engine
        # passed in by a caller (a test reusing tests/conftest.py's
        # fixture-managed session) is that caller's to close, not ours;
        # closing it here would break any assertions the caller still
        # wants to make against it afterward.
        if owns_session:
            await session.close()
            await db_base.dispose_engine()


def main() -> None:
    created = asyncio.run(run())
    if created:
        log.info(
            "generated %d recurring invoice draft(s): %s",
            len(created),
            ", ".join(created),
        )
    else:
        log.info("no recurring invoices due")


if __name__ == "__main__":
    main()
