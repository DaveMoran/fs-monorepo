"""Result models for the income-determination service.

These are **analytics domain objects** — plain Pydantic models in snake_case, not FDX wire
types.  They are kept frozen (immutable) so the service can return them as value objects without
callers accidentally mutating intermediate state.  All collections use ``tuple`` rather than
``list`` so equality and hash behaviour are deterministic, which is important because tests assert
identical results for identical inputs.

Enums use :class:`~enum.StrEnum` so they can be used as literal strings in log messages and JSON
without an extra ``.value`` call.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict


class PayCadence(StrEnum):
    """The detected periodicity of a deposit stream."""

    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"
    MONTHLY = "MONTHLY"
    IRREGULAR = "IRREGULAR"


class ConfidenceLevel(StrEnum):
    """A human-readable band on the detection confidence score."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IncomeStatus(StrEnum):
    """Top-level outcome of an :func:`~banking_client.analytics.income.IncomeService.estimate_regular_income` call."""

    DETECTED = "DETECTED"
    """At least one recurring income source was found."""
    NO_RECURRING_INCOME = "NO_RECURRING_INCOME"
    """Credits exist but none met the recurring-income criteria."""
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    """Fewer than ``MIN_RECURRING_DEPOSITS`` credits in the lookback window."""


class RejectionReason(StrEnum):
    """Why a payee group was excluded from the income estimate."""

    EXCLUDED_COUNTERPARTY = "EXCLUDED_COUNTERPARTY"
    """Payee is a P2P or internal-transfer counterparty (e.g. VENMO, INTERNAL TRANSFER)."""
    SINGLE_OCCURRENCE = "SINGLE_OCCURRENCE"
    """Only one deposit seen — not enough data to assess recurrence."""


# ---------------------------------------------------------------------------
# Banded confidence thresholds (used in income.py; exposed here for tests)
# ---------------------------------------------------------------------------
CONFIDENCE_HIGH: Final[float] = 0.75
CONFIDENCE_MEDIUM: Final[float] = 0.50


class IncomeSource(BaseModel):
    """A single detected income stream (recurring or irregular).

    The ``supporting_transaction_ids`` field provides **explainability** — the agent and eval
    harness can verify the reasoning by inspecting the actual transactions that grounded each
    conclusion.

    Args:
        payee: Normalized counterparty name.
        cadence: Detected periodicity.
        is_recurring: ``True`` when the stream met the full recurring-income criteria (regular
            cadence, sufficient count, stable or single-step amounts).  ``False`` for irregular
            secondary sources.
        per_period_amount: The representative per-deposit amount at the *current* level (post-
            raise, if one was detected).  Uses ``Decimal`` for exact monetary arithmetic.
        estimated_monthly_amount: ``per_period_amount`` normalized to a monthly figure.
        deposit_count: Number of qualifying deposits in the lookback window.
        first_seen: ``posted_timestamp`` of the earliest deposit.
        last_seen: ``posted_timestamp`` of the most recent deposit.
        raise_detected: ``True`` when a single upward step (> ``AMOUNT_TOLERANCE``) was found
            separating two internally-stable amount plateaus.
        prior_period_amount: Amount before the detected raise; ``None`` if no raise.
        confidence: Banded confidence label derived from ``confidence_score``.
        confidence_score: Raw score in ``[0, 1]`` combining regularity, deposit count, and
            amount stability.
        supporting_transaction_ids: Ids of every deposit that contributed to this source.
    """

    model_config = ConfigDict(frozen=True)

    payee: str
    cadence: PayCadence
    is_recurring: bool
    per_period_amount: Decimal
    estimated_monthly_amount: Decimal
    deposit_count: int
    first_seen: datetime
    last_seen: datetime
    raise_detected: bool
    prior_period_amount: Decimal | None
    confidence: ConfidenceLevel
    confidence_score: float
    supporting_transaction_ids: tuple[str, ...]


class RejectedCandidate(BaseModel):
    """A payee group that was examined but excluded from the income estimate.

    Args:
        payee: Normalized counterparty name.
        deposit_count: Number of CREDITs seen from this payee.
        reason: Why the group was excluded.
        sample_transaction_ids: A representative sample of the deposits (up to 5 ids), for
            transparency.
    """

    model_config = ConfigDict(frozen=True)

    payee: str
    deposit_count: int
    reason: RejectionReason
    sample_transaction_ids: tuple[str, ...]


class IncomeEstimate(BaseModel):
    """The complete income-determination result for one or more accounts.

    Args:
        status: Top-level outcome — whether regular income was detected.
        as_of: The reference date the lookback window is anchored to.
        lookback_months: Number of months of history analysed.
        account_ids: The accounts whose transactions were examined.
        estimated_monthly_income: The primary source's monthly income, or ``None`` unless
            ``status`` is ``DETECTED``.
        primary_source: The highest-value recurring income stream, or ``None`` unless
            ``status`` is ``DETECTED``.
        additional_sources: Non-primary sources (recurring or irregular) surfaced for
            transparency.  Includes irregular income (e.g. freelance) that did not meet the
            recurring bar.
        rejected_sources: Payee groups that were examined and explicitly excluded, with a
            reason for each.  Includes P2P counterparties and single-occurrence deposits.
    """

    model_config = ConfigDict(frozen=True)

    status: IncomeStatus
    as_of: datetime
    lookback_months: int
    account_ids: tuple[str, ...]
    estimated_monthly_income: Decimal | None
    primary_source: IncomeSource | None
    additional_sources: tuple[IncomeSource, ...]
    rejected_sources: tuple[RejectedCandidate, ...]
