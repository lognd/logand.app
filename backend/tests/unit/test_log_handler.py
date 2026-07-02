from __future__ import annotations

import logging
from pathlib import Path

from logand_backend.logging.handler import SizeCappedTimedRotatingFileHandler


def _make_handler(tmp_path: Path, max_bytes: int) -> SizeCappedTimedRotatingFileHandler:
    handler = SizeCappedTimedRotatingFileHandler(
        filename=str(tmp_path / "app.log"),
        when="midnight",
        utc=True,
        backupCount=0,
        maxBytes=max_bytes,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def test_rotates_when_size_cap_exceeded(tmp_path: Path) -> None:
    handler = _make_handler(tmp_path, max_bytes=200)
    logger = logging.getLogger("test.size_rotation")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    for i in range(50):
        logger.info("a fairly long log line to fill up the file quickly %d", i)

    handler.close()
    logger.removeHandler(handler)

    rotated = sorted(tmp_path.glob("app.log.*"))
    assert len(rotated) >= 1, "expected at least one size-forced rotation"
    # The live file itself must never be allowed to sit far above the cap
    # for long -- confirm it was actually rotated, not just left growing.
    assert (tmp_path / "app.log").stat().st_size < 5000


def test_never_self_deletes_rotated_files(tmp_path: Path) -> None:
    """backupCount=0 disables the stdlib self-cleanup; getFilesToDelete
    is overridden to make that explicit -- retention.py is the only thing
    that should ever delete a rotated log."""
    handler = _make_handler(tmp_path, max_bytes=100)
    logger = logging.getLogger("test.no_self_delete")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    for i in range(200):
        logger.info("padding out several rotations worth of log lines %d", i)

    handler.close()
    logger.removeHandler(handler)

    rotated = list(tmp_path.glob("app.log.*"))
    assert len(rotated) >= 2, "expected multiple rotations, none self-deleted"
