from __future__ import annotations

from datetime import date

import pytest

from logand_backend.domain.invoices.recurrence import _advance


def test_advance_weekly() -> None:
    assert _advance(date(2026, 1, 1), "weekly") == date(2026, 1, 8)


def test_advance_monthly() -> None:
    assert _advance(date(2026, 1, 15), "monthly") == date(2026, 2, 15)


def test_advance_monthly_rolls_over_year_boundary() -> None:
    assert _advance(date(2026, 12, 15), "monthly") == date(2027, 1, 15)


def test_advance_quarterly() -> None:
    assert _advance(date(2026, 1, 15), "quarterly") == date(2026, 4, 15)


def test_advance_yearly() -> None:
    assert _advance(date(2026, 6, 30), "yearly") == date(2027, 6, 30)


def test_advance_monthly_clamps_31_day_month_to_30_day_month() -> None:
    # Jan 31 + 1 month -> Feb has at most 28/29 days, must clamp, not raise.
    assert _advance(date(2026, 1, 31), "monthly") == date(2026, 2, 28)


def test_advance_monthly_from_leap_day() -> None:
    # 2028 is a leap year; Jan 31 -> Feb 29.
    assert _advance(date(2028, 1, 31), "monthly") == date(2028, 2, 29)


def test_advance_yearly_from_leap_day_clamps_to_non_leap_year() -> None:
    # 2028 is a leap year, 2029 is not -- Feb 29 has no equivalent.
    assert _advance(date(2028, 2, 29), "yearly") == date(2029, 2, 28)


def test_advance_rejects_unrecognized_interval() -> None:
    with pytest.raises(ValueError):
        _advance(date(2026, 1, 1), "biweekly")


def test_advance_rejects_none_interval() -> None:
    with pytest.raises(ValueError):
        _advance(date(2026, 1, 1), None)
