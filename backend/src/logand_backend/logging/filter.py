from __future__ import annotations

import logging


class BelowLevelFilter(logging.Filter):
    """Pass records strictly below `below` level (used to keep stdout clean)."""

    def __init__(self, below: str) -> None:
        super().__init__()
        self._below = logging.getLevelName(below)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self._below
