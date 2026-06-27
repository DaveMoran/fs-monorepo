"""Shared cadence-detection and statistical primitives for analytics services.

Both the income-determination service (:mod:`banking_client.analytics.income`) and the
spending-analysis service (:mod:`banking_client.analytics.spending`) classify transaction
cadence, measure regularity, and perform exact Decimal arithmetic.  This module extracts those
pure, stateless helpers so they are implemented once and reused without creating a direct
dependency between the two services.

All functions here are deliberately side-effect free: no I/O, no randomness, no external state.
Given identical inputs they always return identical outputs.

Design note
-----------
This is an internal ``_`` module — its public surface is consumed by the two analytics services
and their test suites only.  External callers should import analytics types from
:mod:`banking_client.analytics` rather than from this module directly.
"""

from __future__ import annotations

import statistics
from calendar import monthrange
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from banking_client.analytics.results import PayCadence

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

AMOUNT_TOLERANCE: Final[Decimal] = Decimal("0.10")
"""Maximum relative deviation (10 %) from a plateau median in amount-stability checks."""

REGULARITY_THRESHOLD: Final[float] = 0.60
"""Minimum fraction of gaps within ±25 % of the cadence period to qualify as recurring."""

# ---------------------------------------------------------------------------
# Cadence buckets
# ---------------------------------------------------------------------------

#: (min_days, max_days, cadence, period_days) — ordered from shortest to longest.
_CADENCE_BUCKETS: Final[list[tuple[float, float, PayCadence, float]]] = [
    (5.0, 10.0, PayCadence.WEEKLY, 7.0),
    (11.0, 17.0, PayCadence.BIWEEKLY, 14.0),
    (25.0, 35.0, PayCadence.MONTHLY, 30.0),
]

_MONTHLY_FACTOR: Final[dict[PayCadence, Decimal]] = {
    PayCadence.WEEKLY: Decimal("52") / Decimal("12"),
    PayCadence.BIWEEKLY: Decimal("26") / Decimal("12"),
    PayCadence.SEMIMONTHLY: Decimal("24") / Decimal("12"),
    PayCadence.MONTHLY: Decimal("1"),
    PayCadence.IRREGULAR: Decimal("1"),  # Irregular sources: caller controls monthly estimation.
}
"""Per-cadence multiplier that normalises a per-period amount to a monthly figure."""


# ---------------------------------------------------------------------------
# Window / date helpers
# ---------------------------------------------------------------------------


def _window_start(as_of: datetime, months: int) -> datetime:
    """Return the datetime *months* before *as_of* with the day clamped to a valid value.

    Replicates the logic in ``fixtures.generator.schedule.window_start`` without importing
    from ``fixtures``.  The ``src`` tree must never depend on ``fixtures``.

    Args:
        as_of: The anchor (upper end of the lookback window).
        months: How many calendar months to look back.

    Returns:
        A datetime preserving the tzinfo, hour, minute, second, and microsecond of *as_of*,
        shifted *months* calendar months into the past (day clamped to month end on short months).
    """
    index = as_of.year * 12 + (as_of.month - 1) - months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    day = min(as_of.day, monthrange(year, month)[1])
    return as_of.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Payee normalization
# ---------------------------------------------------------------------------


def _normalize_payee(payee: str | None) -> str:
    """Return the upper-cased, stripped payee, or ``"UNKNOWN"`` for ``None``.

    Args:
        payee: Raw payee string from the transaction.

    Returns:
        Canonical form used for grouping and exclusion checks.
    """
    return payee.strip().upper() if payee is not None else "UNKNOWN"


# ---------------------------------------------------------------------------
# Cadence detection
# ---------------------------------------------------------------------------


def _detect_cadence(gaps: list[float]) -> tuple[PayCadence, float]:
    """Classify a list of inter-transaction gap durations (in days) into a cadence bucket.

    Uses the *median* gap so that a few outliers (e.g. a holiday delay) do not shift the whole
    classification.

    Args:
        gaps: Consecutive inter-transaction durations in days.  Must be non-empty for a
            non-IRREGULAR result; an empty list always returns ``(IRREGULAR, 0.0)``.

    Returns:
        ``(cadence, period_days)`` where *period_days* is the bucket's canonical period.
        Returns ``(IRREGULAR, median_gap)`` when the median falls outside all buckets.
    """
    if not gaps:
        return PayCadence.IRREGULAR, 0.0
    median_gap = statistics.median(gaps)
    for lo, hi, cadence, period in _CADENCE_BUCKETS:
        if lo <= median_gap <= hi:
            return cadence, period
    return PayCadence.IRREGULAR, float(median_gap)


def _regularity(gaps: list[float], period: float) -> float:
    """Return the fraction of gaps within ±25 % (min ±4 days) of the cadence period.

    Args:
        gaps: Inter-transaction durations in days.
        period: Canonical cadence period in days.

    Returns:
        Float in ``[0.0, 1.0]``.  ``0.0`` when *gaps* is empty or *period* is zero.
    """
    if not gaps or period == 0.0:
        return 0.0
    tolerance = max(period * 0.25, 4.0)
    count = sum(1 for g in gaps if abs(g - period) <= tolerance)
    return count / len(gaps)


# ---------------------------------------------------------------------------
# Decimal statistics
# ---------------------------------------------------------------------------


def _decimal_median(amounts: list[Decimal]) -> Decimal:
    """Return the median of a non-empty list of ``Decimal`` values (exact arithmetic).

    Args:
        amounts: Non-empty list of Decimal amounts.

    Returns:
        Median value quantized to two decimal places.  Returns ``Decimal("0.00")`` for an
        empty list (degenerate guard; callers should validate non-empty before calling).
    """
    sorted_amounts = sorted(amounts)
    n = len(sorted_amounts)
    if n == 0:
        return Decimal("0.00")
    if n % 2 == 1:
        return sorted_amounts[n // 2]
    mid = (sorted_amounts[n // 2 - 1] + sorted_amounts[n // 2]) / Decimal("2")
    return mid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_stable_plateau(amounts: list[Decimal]) -> bool:
    """Return ``True`` if all amounts are within ``AMOUNT_TOLERANCE`` of the median.

    A single-element list is trivially stable.

    Args:
        amounts: Non-empty list of amounts on one plateau.

    Returns:
        ``True`` when the plateau is internally consistent.
    """
    if len(amounts) == 0:
        return False
    if len(amounts) == 1:
        return True
    m = _decimal_median(amounts)
    if m == Decimal("0"):
        return True  # All zeros — degenerate but stable.
    return all(abs(a - m) <= m * AMOUNT_TOLERANCE for a in amounts)


def _amount_stability(plateau: tuple[Decimal, ...]) -> float:
    """Return an amount-stability score in ``[0.0, 1.0]``.

    ``1.0`` means perfectly stable (e.g. an exact subscription charge).  Score decreases as the
    coefficient of variation (σ/μ) of the plateau amounts increases.

    Args:
        plateau: Representative amounts (the current plateau for income; all amounts for spend).

    Returns:
        Stability score in ``[0.0, 1.0]``.
    """
    if len(plateau) <= 1:
        return 1.0
    values = [float(a) for a in plateau]
    mean_val = statistics.mean(values)
    if mean_val == 0.0:
        return 1.0
    pstdev_val = statistics.pstdev(values)
    cv = pstdev_val / mean_val
    return max(0.0, 1.0 - min(cv, 1.0))


# ---------------------------------------------------------------------------
# Monthly normalisation
# ---------------------------------------------------------------------------


def _to_monthly(per_period: Decimal, cadence: PayCadence) -> Decimal:
    """Normalise a per-period amount to an estimated monthly figure.

    Args:
        per_period: The representative per-occurrence amount.
        cadence: The detected cadence.

    Returns:
        Monthly equivalent, quantized to two decimal places.
    """
    factor = _MONTHLY_FACTOR[cadence]
    return (per_period * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
