from __future__ import annotations

import logging
import sys

# A real stdlib logging.Logger underneath -- ok()/warn()/fail() are just
# logger.info()/warning()/error() with the vocabulary this script's
# checks actually use. Deliberately distinct from ~/.claude/refs/logging.md's
# app-wide dictConfig setup (logging/logger.py) -- that one is tuned for
# structured/JSON production log aggregation, this is a human reading a
# terminal right now, so plain leveled + colored console output is the
# right formatter here, not the app's own.


class _CountingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.warnings = 0
        self.errors = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno == logging.WARNING:
            self.warnings += 1
        elif record.levelno >= logging.ERROR:
            self.errors += 1


class _PrettyFormatter(logging.Formatter):
    _LABELS = {logging.INFO: "OK", logging.WARNING: "WARN", logging.ERROR: "FAIL"}
    _COLORS = {
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
    }
    _RESET = "\033[0m"
    _BOLD = "\033[1m"

    def __init__(self, use_color: bool) -> None:
        super().__init__()
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "section", False):
            msg = record.getMessage()
            return (
                f"\n{self._BOLD}== {msg} =={self._RESET}"
                if self._use_color
                else f"\n== {msg} =="
            )
        label = self._LABELS.get(record.levelno, record.levelname)
        msg = record.getMessage()
        if self._use_color:
            color = self._COLORS.get(record.levelno, "")
            return f"  {color}[{label:>4}]{self._RESET} {msg}"
        return f"  [{label:>4}] {msg}"


class HealthLogger:
    def __init__(self, logger: logging.Logger, counter: _CountingHandler) -> None:
        self._logger = logger
        self._counter = counter

    def ok(self, message: str) -> None:
        self._logger.info(message)

    def warn(self, message: str) -> None:
        self._logger.warning(message)

    def fail(self, message: str) -> None:
        self._logger.error(message)

    def section(self, title: str) -> None:
        self._logger.info(title, extra={"section": True})

    def summary(self, all_ok: bool) -> None:
        del all_ok  # the counter (warnings/errors actually emitted) is authoritative
        self.section("Summary")
        if self._counter.errors:
            self.fail(
                f"{self._counter.errors} check(s) FAILED -- see above. "
                "This deployment is not healthy."
            )
        elif self._counter.warnings:
            self.warn(
                f"{self._counter.warnings} check(s) degraded-but-expected "
                "(see WARN above) -- nothing broken, but review before you "
                "consider this fully configured."
            )
        else:
            self.ok("Every check passed cleanly -- no warnings, no failures.")


def get_health_logger() -> HealthLogger:
    logger = logging.getLogger("logand.health_check")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    counter = next(
        (h for h in logger.handlers if isinstance(h, _CountingHandler)), None
    )
    if counter is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_PrettyFormatter(use_color=sys.stdout.isatty()))
        logger.addHandler(handler)
        counter = _CountingHandler()
        logger.addHandler(counter)
    return HealthLogger(logger, counter)
