"""Result models for the analytics services (income-determination and spending-analysis).

These are **analytics domain objects** — plain Pydantic models in snake_case, not FDX wire
types.  They are kept frozen (immutable) so the services can return them as value objects without
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


# ===========================================================================
# Spending-analysis result models
# ===========================================================================


class SpendingStatus(StrEnum):
    """Top-level outcome of a :meth:`~banking_client.analytics.spending.SpendingService.analyze_spending` call."""

    ANALYZED = "ANALYZED"
    """At least one POSTED debit transaction was found and analysed."""
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    """No POSTED debit transactions in the lookback window."""


class NotableKind(StrEnum):
    """Why a transaction was surfaced in the notable items list."""

    LARGE_ONE_OFF = "LARGE_ONE_OFF"
    """The amount is a statistical outlier relative to the category's typical variable spend
    (more than :data:`~banking_client.analytics.spending.OUTLIER_MULTIPLE` × the category
    median).  Excluded from the variable monthly average so it does not distort comparisons."""
    REFUND = "REFUND"
    """An inbound CREDIT with category ``CAT-REFUND``.  Netted against gross spend in
    :attr:`~SpendingAnalysis.total_net_spend`."""


class SpendCategorySummary(BaseModel):
    """Aggregated spending across all payees in one transaction category.

    Args:
        category_id: Stable category identifier (e.g. ``"CAT-GROCERIES"``).
        category_name: Human-readable category label (e.g. ``"Groceries"``).
        total_spend: Gross total of all DEBIT amounts in the category for the lookback window,
            including any one-off outlier amounts (so numbers reconcile to the raw data).
        recurring_monthly_average: Average monthly spend excluding any flagged
            :attr:`~NotableKind.LARGE_ONE_OFF` amounts.  Computed as
            ``(total_spend − flagged_amounts) / lookback_months``.
        transaction_count: Number of DEBIT transactions in the category (excluding
            transfers and refunds).
        is_fixed: ``True`` when at least one ``(category, payee)`` group within this category
            qualifies as a recurring fixed cost (i.e. appears in
            :attr:`SpendingAnalysis.recurring_costs`).
        supporting_transaction_ids: Ids of every DEBIT transaction contributing to
            ``total_spend``.
    """

    model_config = ConfigDict(frozen=True)

    category_id: str
    category_name: str
    total_spend: Decimal
    recurring_monthly_average: Decimal
    transaction_count: int
    is_fixed: bool
    supporting_transaction_ids: tuple[str, ...]


class RecurringCost(BaseModel):
    """A single fixed recurring expense detected via structural cadence analysis.

    A ``(category, payee)`` group qualifies as a recurring cost when the same payee appears at
    a regular cadence (weekly / biweekly / monthly) across the lookback window.

    Args:
        payee: Normalized counterparty name.
        category_id: Stable category identifier.
        category_name: Human-readable category label.
        cadence: Detected periodicity.
        average_amount: Median per-occurrence amount (exact Decimal arithmetic).
        estimated_monthly_amount: ``average_amount`` normalised to a monthly equivalent.
        occurrence_count: Number of occurrences in the lookback window.
        supporting_transaction_ids: Ids of every occurrence contributing to this cost.
    """

    model_config = ConfigDict(frozen=True)

    payee: str
    category_id: str
    category_name: str
    cadence: PayCadence
    average_amount: Decimal
    estimated_monthly_amount: Decimal
    occurrence_count: int
    supporting_transaction_ids: tuple[str, ...]


class NotableItem(BaseModel):
    """A transaction flagged for special treatment (outlier or refund).

    Args:
        transaction_id: Stable transaction identifier.
        kind: Whether this is a :attr:`~NotableKind.LARGE_ONE_OFF` or a :attr:`~NotableKind.REFUND`.
        payee: Normalized payee name.
        category_id: Category identifier of the transaction.
        category_name: Human-readable category label, or ``None`` if uncategorized.
        amount: Transaction amount (always positive; direction is given by *kind*).
        posted: Settlement timestamp.
        note: Human-readable explanation (e.g. ``"3.1× category median; excluded from avg"``).
    """

    model_config = ConfigDict(frozen=True)

    transaction_id: str
    kind: NotableKind
    payee: str
    category_id: str | None
    category_name: str | None
    amount: Decimal
    posted: datetime
    note: str


class SpendingAnalysis(BaseModel):
    """The complete spending-analysis result for one or more accounts.

    All monetary figures use ``Decimal`` for exact arithmetic and are quantized to two decimal
    places.  Monthly averages are computed by dividing totals by ``lookback_months``, so a month
    with no transactions correctly lowers the average rather than being silently excluded.

    Relationships between totals::

        total_net_spend  = total_gross_spend − total_refunds
        typical_monthly_spend ≈ fixed_monthly_total + variable_monthly_total
        (transfers and one-offs are intentionally excluded from typical_monthly_spend)

    Args:
        status: Top-level outcome.
        as_of: The reference date the lookback window is anchored to.
        lookback_months: Number of months of history analysed.
        account_ids: The accounts whose transactions were examined.
        total_gross_spend: Sum of ALL DEBIT amounts in the window (incl. one-offs and transfers).
        total_refunds: Sum of REFUND-category CREDIT amounts netted against spend.
        total_net_spend: ``total_gross_spend − total_refunds``.
        fixed_monthly_total: Sum of recurring fixed cost monthly equivalents.
        variable_monthly_total: Average monthly variable spend *excluding* one-off outliers.
        typical_monthly_spend: ``fixed_monthly_total + variable_monthly_total`` — the
            distortion-free headline spend excluding one-offs, refunds, and transfers.
        transfers_monthly_total: Average monthly self-transfer outflow (savings, etc.) —
            excluded from all spend figures but surfaced for completeness.
        category_breakdown: One :class:`SpendCategorySummary` per spend category observed.
        recurring_costs: Fixed/recurring ``(category, payee)`` groups that cleared the cadence
            and regularity bar.
        notable_items: Flagged transactions (:attr:`~NotableKind.LARGE_ONE_OFF` and
            :attr:`~NotableKind.REFUND`).
    """

    model_config = ConfigDict(frozen=True)

    status: SpendingStatus
    as_of: datetime
    lookback_months: int
    account_ids: tuple[str, ...]
    total_gross_spend: Decimal
    total_refunds: Decimal
    total_net_spend: Decimal
    fixed_monthly_total: Decimal
    variable_monthly_total: Decimal
    typical_monthly_spend: Decimal
    transfers_monthly_total: Decimal
    category_breakdown: tuple[SpendCategorySummary, ...]
    recurring_costs: tuple[RecurringCost, ...]
    notable_items: tuple[NotableItem, ...]
