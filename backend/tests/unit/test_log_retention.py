from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from logand_backend.logging.retention import prune_logs


def _make(log_dir: Path, day: date, size: int = 100, suffix: str = "") -> Path:
    name = f"app.log.{day.isoformat()}"
    if suffix:
        name += f".{suffix}"
    path = log_dir / name
    path.write_bytes(b"x" * size)
    return path


def test_keeps_all_files_within_daily_window(tmp_path: Path) -> None:
    today = date(2026, 7, 2)
    kept = [_make(tmp_path, today - timedelta(days=d)) for d in range(7)]

    deleted = prune_logs(tmp_path, today=today, keep_daily=7, hard_cap_bytes=10**9)

    assert deleted == []
    assert all(p.exists() for p in kept)


def test_thins_older_files_to_weekly_then_monthly(tmp_path: Path) -> None:
    today = date(2026, 7, 2)
    # Every single day for the last 100 days -- realistic "been running a
    # while" history.
    for d in range(100):
        _make(tmp_path, today - timedelta(days=d))

    prune_logs(
        tmp_path,
        today=today,
        keep_daily=7,
        keep_weekly=8,
        keep_monthly=12,
        hard_cap_bytes=10**9,
    )

    remaining = sorted(p.name for p in tmp_path.glob("app.log.*"))
    # Far fewer than the 100 originally written -- thinned, not kept whole.
    assert len(remaining) < 30
    # The most recent 7 days must all still be present, untouched.
    for d in range(7):
        assert f"app.log.{(today - timedelta(days=d)).isoformat()}" in remaining


def test_deletes_files_older_than_every_retention_bucket(tmp_path: Path) -> None:
    today = date(2026, 7, 2)
    ancient = _make(tmp_path, today - timedelta(days=800))

    deleted = prune_logs(
        tmp_path,
        today=today,
        keep_daily=7,
        keep_weekly=8,
        keep_monthly=12,
        hard_cap_bytes=10**9,
    )

    assert ancient in deleted
    assert not ancient.exists()


def test_hard_cap_deletes_oldest_survivors_first_regardless_of_schedule(
    tmp_path: Path,
) -> None:
    today = date(2026, 7, 2)
    # All within the "keep daily" window, so the exponential schedule
    # alone would keep every one of them -- but each is oversized, so the
    # hard cap must still kick in and trim the oldest.
    files = [_make(tmp_path, today - timedelta(days=d), size=1000) for d in range(7)]

    deleted = prune_logs(tmp_path, today=today, keep_daily=7, hard_cap_bytes=4000)

    assert len(deleted) > 0
    total_remaining = sum(p.stat().st_size for p in files if p.exists())
    assert total_remaining <= 4000
    # The newest file must never be the one sacrificed to the cap.
    assert files[0].exists()


def test_never_touches_the_live_log_file(tmp_path: Path) -> None:
    live = tmp_path / "app.log"
    live.write_bytes(b"still being written")
    today = date(2026, 7, 2)
    _make(tmp_path, today - timedelta(days=900))

    prune_logs(tmp_path, today=today, hard_cap_bytes=0)

    assert live.exists()


def test_multiple_same_day_size_rotations_bucket_together(tmp_path: Path) -> None:
    today = date(2026, 7, 2)
    ancient_day = today - timedelta(days=900)
    a = _make(tmp_path, ancient_day, suffix="1")
    b = _make(tmp_path, ancient_day, suffix="2")

    deleted = prune_logs(tmp_path, today=today, hard_cap_bytes=10**9)

    assert a in deleted
    assert b in deleted
