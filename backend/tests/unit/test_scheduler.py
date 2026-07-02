from __future__ import annotations

from datetime import datetime, timezone

from logand_backend.scripts.scheduler import seconds_until_next_run


def test_seconds_until_next_run_same_day_before_target() -> None:
    now = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    assert seconds_until_next_run(now, run_hour_utc=4) == 2 * 3600


def test_seconds_until_next_run_same_day_at_exact_target_rolls_to_tomorrow() -> None:
    # <= target, not < -- exactly on the hour must not return 0 and spin.
    now = datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc)
    assert seconds_until_next_run(now, run_hour_utc=4) == 24 * 3600


def test_seconds_until_next_run_after_target_rolls_to_tomorrow() -> None:
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert seconds_until_next_run(now, run_hour_utc=4) == 18 * 3600


def test_seconds_until_next_run_crosses_month_boundary() -> None:
    now = datetime(2026, 1, 31, 23, 0, tzinfo=timezone.utc)
    assert seconds_until_next_run(now, run_hour_utc=4) == 5 * 3600
