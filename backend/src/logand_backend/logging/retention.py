from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

# Exponential-backoff retention for the daily-rotated log files written by
# logging/handler.py's TimedRotatingFileHandler (suffix "app.log.YYYY-MM-DD").
# Same idea as ops/backup.sh's off-box pruning -- keep everything recent at
# full density, then thin older history to a sparser and sparser sample --
# but time-bucketed (daily -> weekly -> monthly) rather than a flat "keep
# the N most recent," since unlike the backup script's fixed-count backups,
# log files are naturally one-per-day and thinning by calendar bucket is
# the meaningful "exponential" shape here.
# The optional trailing ".N" covers handler.py's mid-day size-forced
# rotations (e.g. "app.log.2026-07-02.1") -- still bucketed by date only,
# so a day with several size-triggered rotations is treated as one day
# for retention purposes, exactly like a quiet day with just one file.
_ROTATED_SUFFIX_RE = re.compile(r"\.(\d{4}-\d{2}-\d{2})(?:\.\d+)?$")

DEFAULT_KEEP_DAILY = 7
DEFAULT_KEEP_WEEKLY = 8
DEFAULT_KEEP_MONTHLY = 12
# Hard backstop -- even if the exponential schedule above would keep more,
# never let the ON-DISK total exceed this. This is what makes "logs can
# never overflow memory/disk" true regardless of log volume or whether the
# prune job has run recently; the exponential schedule handles the common
# case, this handles the pathological one.
DEFAULT_HARD_CAP_BYTES = 500 * 1024 * 1024


class RotatedLogFile(BaseModel):
    model_config = {"frozen": True}

    path: Path
    log_date: date
    size_bytes: int


def _parse_rotated_files(log_dir: Path, base_name: str) -> list[RotatedLogFile]:
    files = []
    for path in log_dir.glob(f"{base_name}.*"):
        match = _ROTATED_SUFFIX_RE.search(path.name)
        if not match:
            continue
        log_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        files.append(
            RotatedLogFile(
                path=path, log_date=log_date, size_bytes=path.stat().st_size
            )
        )
    return files


def _keep_set(
    files: list[RotatedLogFile],
    today: date,
    keep_daily: int,
    keep_weekly: int,
    keep_monthly: int,
) -> set[Path]:
    keep: set[Path] = set()
    daily_cutoff = today - timedelta(days=keep_daily)
    weekly_cutoff = daily_cutoff - timedelta(weeks=keep_weekly)
    monthly_cutoff = weekly_cutoff - timedelta(days=30 * keep_monthly)

    weekly_buckets: dict[int, RotatedLogFile] = {}
    monthly_buckets: dict[tuple[int, int], RotatedLogFile] = {}

    for f in sorted(files, key=lambda f: f.log_date):
        if f.log_date > daily_cutoff:
            keep.add(f.path)
        elif f.log_date > weekly_cutoff:
            # One survivor per ISO week -- first (oldest) file seen in that
            # week wins, giving evenly-spaced samples through the month.
            bucket_key = f.log_date.isocalendar()[1]
            weekly_buckets.setdefault(bucket_key, f)
        elif f.log_date > monthly_cutoff:
            bucket_key = (f.log_date.year, f.log_date.month)
            monthly_buckets.setdefault(bucket_key, f)
        # else: older than every bucket -- not kept at all.

    keep.update(f.path for f in weekly_buckets.values())
    keep.update(f.path for f in monthly_buckets.values())
    return keep


def prune_logs(
    log_dir: Path,
    base_name: str = "app.log",
    today: date | None = None,
    keep_daily: int = DEFAULT_KEEP_DAILY,
    keep_weekly: int = DEFAULT_KEEP_WEEKLY,
    keep_monthly: int = DEFAULT_KEEP_MONTHLY,
    hard_cap_bytes: int = DEFAULT_HARD_CAP_BYTES,
) -> list[Path]:
    """Deletes rotated log files outside the exponential retention
    schedule, then -- regardless of that schedule -- deletes the oldest
    still-kept files until total size is under hard_cap_bytes. Returns
    every path actually deleted. The live (currently being written)
    `base_name` file itself is never touched here.
    """
    today = today or datetime.now().date()
    files = _parse_rotated_files(log_dir, base_name)
    keep = _keep_set(files, today, keep_daily, keep_weekly, keep_monthly)

    deleted: list[Path] = []
    survivors: list[RotatedLogFile] = []
    for f in files:
        if f.path in keep:
            survivors.append(f)
        else:
            f.path.unlink(missing_ok=True)
            deleted.append(f.path)

    total_size = sum(f.size_bytes for f in survivors)
    if total_size > hard_cap_bytes:
        for f in sorted(survivors, key=lambda f: f.log_date):
            if total_size <= hard_cap_bytes:
                break
            f.path.unlink(missing_ok=True)
            deleted.append(f.path)
            total_size -= f.size_bytes

    return deleted
