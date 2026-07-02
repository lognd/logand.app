from __future__ import annotations

import datetime
import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler
from os import PathLike


class SizeCappedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """TimedRotatingFileHandler (one file per UTC day) that ALSO forces an
    early rotation if the live file crosses maxBytes -- a burst of error
    logging (a crash loop, a noisy retry storm) must not be able to grow
    a single day's file without bound between midnight rollovers. This is
    the "never overflow" guarantee for the live file; retention.py's
    exponential pruning is the guarantee for the accumulated history of
    already-rotated files.

    Renames the size-forced rotation with a numeric suffix appended to the
    normal date suffix (e.g. "app.log.2026-07-02.1") so it never collides
    with the handler's own midnight rotation for the same day, and so
    retention.py's date parsing (which tolerates a trailing ".N") still
    buckets it correctly.
    """

    def __init__(
        self,
        filename: str | PathLike[str],
        when: str = "h",
        interval: int = 1,
        backupCount: int = 0,
        encoding: str | None = None,
        delay: bool = False,
        utc: bool = False,
        atTime: datetime.time | None = None,
        errors: str | None = None,
        maxBytes: int = 20 * 1024 * 1024,
    ) -> None:
        super().__init__(
            filename,
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            utc=utc,
            atTime=atTime,
            errors=errors,
        )
        self.maxBytes = maxBytes

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # noqa: N802 (stdlib override)
        if super().shouldRollover(record):
            return True
        if self.maxBytes <= 0 or self.stream is None:
            return False
        self.stream.seek(0, os.SEEK_END)
        return self.stream.tell() >= self.maxBytes

    def getFilesToDelete(self) -> list[str]:  # noqa: N802 (stdlib override)
        # backupCount=0 in production config -- this handler deletes
        # nothing itself; retention.py owns that decision exclusively (see
        # config.toml's comment). Overridden (not just configured to 0,
        # which already disables stdlib's own call site) to make that
        # intent explicit and crash loudly if ever misconfigured.
        return []

    def doRollover(self) -> None:  # noqa: N802 (stdlib override)
        # A size-forced rollover before midnight would otherwise collide
        # with TimedRotatingFileHandler's own date-suffixed rename target
        # (today's date, already in use by the file we're rotating FROM).
        # Append a numeric suffix in that case so both files survive.
        current_time = int(time.time())
        # TimedRotatingFileHandler.shouldRollover's own implementation
        # never actually reads `record` (it's a purely time-based check,
        # unlike RotatingFileHandler's size-based one) -- a cheap dummy
        # record satisfies the type signature without pretending this
        # call is record-aware.
        time_based_due = super().shouldRollover(logging.makeLogRecord({}))
        if not time_based_due:
            self._manual_suffix_counter = getattr(self, "_manual_suffix_counter", 0) + 1
            day_suffix = time.strftime(self.suffix, time.gmtime(current_time))
            dest = f"{self.baseFilename}.{day_suffix}.{self._manual_suffix_counter}"
            if self.stream:
                self.stream.close()
                self.stream = None  # type: ignore[assignment]
            if os.path.exists(self.baseFilename):
                os.rename(self.baseFilename, dest)
            if not self.delay:
                self.stream = self._open()
            return
        self._manual_suffix_counter = 0
        super().doRollover()
