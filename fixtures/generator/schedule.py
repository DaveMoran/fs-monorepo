"""Deterministic date-schedule helpers for recurring activity.

All occurrence lists are a pure function of the window and cadence — no randomness — so the
recurring backbone (payroll, bills) is perfectly reproducible. Days that overflow a month
(e.g. the 30th in February) are clamped to the month's last valid day.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta

_BIWEEKLY = timedelta(days=14)


def _clamp_day(year: int, month: int, day: int) -> int:
    return min(day, monthrange(year, month)[1])


def window_start(anchor: datetime, months: int) -> datetime:
    """Return the datetime ``months`` before ``anchor`` (day clamped to a valid value)."""
    index = anchor.year * 12 + (anchor.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    return anchor.replace(year=year, month=month, day=_clamp_day(year, month, anchor.day))


def biweekly_occurrences(start: datetime, end: datetime) -> list[datetime]:
    """Every 14th day from ``start`` through ``end`` inclusive (payroll cadence)."""
    out: list[datetime] = []
    current = start
    while current <= end:
        out.append(current)
        current += _BIWEEKLY
    return out


def monthly_occurrences(start: datetime, end: datetime, day_of_month: int) -> list[datetime]:
    """The given day in each month spanned by ``[start, end]`` (bill cadence)."""
    out: list[datetime] = []
    index = start.year * 12 + (start.month - 1)
    end_index = end.year * 12 + (end.month - 1)
    while index <= end_index:
        year, month = divmod(index, 12)
        month += 1
        occurrence = start.replace(year=year, month=month, day=_clamp_day(year, month, day_of_month))
        if start <= occurrence <= end:
            out.append(occurrence)
        index += 1
    return out


def month_anchors(start: datetime, end: datetime) -> list[datetime]:
    """First-of-month datetimes for each month in ``[start, end]`` (for per-month sampling)."""
    return monthly_occurrences(start, end, day_of_month=1)
