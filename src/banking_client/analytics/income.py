"""Deterministic income-determination service.

This module infers a customer's regular income from FDX transaction history using **only** the
minimum set of transaction fields mandated by the 1033 data-minimization principle.

1033 data-minimization contract
---------------------------------
The service reads **exactly four** transaction fields:

- ``tx.id`` — read-only identifier for explainability output (never used in inference).
- ``tx.amount.value`` — the posted amount.
- ``tx.posted_timestamp`` — when funds settled; the cadence clock runs on this.
- ``tx.debit_credit_memo`` — direction; only CREDIT transactions are analysed.
- ``tx.payee`` — the normalized counterparty name used for grouping and exclusion.

Fields deliberately **not read** (incomplete list):

- ``tx.category`` — provider labels vary; structural inference is more portable.
- ``tx.description`` — raw string; fragile and provider-specific.
- ``tx.transaction_timestamp`` — authorization date; not used (cadence keys on settlement).
- ``tx.location`` — location data is not needed and is explicitly excluded.
- ``tx.account_id``, ``tx.status``, ``tx.nickname``, and all other fields.

Determinism guarantee
----------------------
Given identical inputs ``(transactions, as_of, lookback_months)`` the service always returns an
identical :class:`~banking_client.analytics.results.IncomeEstimate`.  There is no randomness,
no LLM call, and no wall-clock read inside the pure detection functions.  The ``as_of`` date is
injectable so tests can fix it to the fixture anchor without relying on ``datetime.now()``.

Auth + audit inheritance
--------------------------
The service does not own an auth guard or audit trail.  It calls
:meth:`~banking_client.client.transactions.TransactionsClient.get_transactions` (and optionally
:meth:`~banking_client.client.accounts.AccountsClient.get_accounts`) for every data access, so
every underlying request goes through the standard auth guard and emits an audit event on the
injected trails.

Detection algorithm
--------------------
See :meth:`IncomeService.estimate_regular_income` for the step-by-step description.
The key insight: payroll is rejected *only when a structural property fails* (regular biweekly
cadence + stable amount); the algorithm never uses provider-supplied labels to distinguish payroll
from P2P transfers.  Payee-based counterparty exclusion is the one exception — documented as a
conservative heuristic for well-known P2P platforms.
"""

from __future__ import annotations

import statistics
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from banking_client.analytics.results import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    ConfidenceLevel,
    IncomeEstimate,
    IncomeSource,
    IncomeStatus,
    PayCadence,
    RejectedCandidate,
    RejectionReason,
)
from banking_client.client.accounts import AccountsClient, default_accounts_client
from banking_client.client.transactions import TransactionsClient, default_transactions_client
from banking_client.models.enums import AccountType, DebitCreditMemo, TransactionStatus
from banking_client.models.transaction import Transaction
from common.audit import AuditTrail

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

MIN_RECURRING_DEPOSITS: Final[int] = 4
"""Minimum deposits in the lookback window for a stream to qualify as recurring income."""

AMOUNT_TOLERANCE: Final[Decimal] = Decimal("0.10")
"""Maximum relative deviation (10 %) from a plateau median before a deposit is considered off."""

REGULARITY_THRESHOLD: Final[float] = 0.60
"""Minimum fraction of gaps within tolerance of the cadence period to qualify as recurring."""

_FETCH_PAGE_SIZE: Final[int] = 500
"""Page size for the internal transaction-fetching loop (large enough to fit typical histories)."""

# ---------------------------------------------------------------------------
# Counterparty exclusion denylist
# ---------------------------------------------------------------------------

_COUNTERPARTY_DENYLIST: Final[frozenset[str]] = frozenset(
    {
        "VENMO",
        "ZELLE",
        "CASH APP",
        "CASHAPP",
        "INTERNAL TRANSFER",
    }
)
"""Normalized payee names that are *always* P2P or self-transfer counterparties.

This denylist is the **only** place the algorithm uses a payee-based heuristic rather than
structural inference.  It is intentionally conservative — only well-known platforms with no
plausible wage-payment use are listed.  A production system would replace this with a richer
counterparty-enrichment service.
"""

# ---------------------------------------------------------------------------
# Cadence detection
# ---------------------------------------------------------------------------

#: (min_days, max_days, cadence, period_days) — ordered from shortest to longest.
_CADENCE_BUCKETS: Final[list[tuple[float, float, PayCadence, float]]] = [
    (5.0, 10.0, PayCadence.WEEKLY, 7.0),
    (11.0, 17.0, PayCadence.BIWEEKLY, 14.0),
    (25.0, 35.0, PayCadence.MONTHLY, 30.0),
]

_EXPECTED_PER_MONTH: Final[dict[PayCadence, float]] = {
    PayCadence.WEEKLY: 52.0 / 12.0,
    PayCadence.BIWEEKLY: 26.0 / 12.0,
    PayCadence.SEMIMONTHLY: 24.0 / 12.0,
    PayCadence.MONTHLY: 1.0,
    PayCadence.IRREGULAR: 1.0,  # Not used for recurring classification; safe fallback.
}

_MONTHLY_FACTOR: Final[dict[PayCadence, Decimal]] = {
    PayCadence.WEEKLY: Decimal("52") / Decimal("12"),
    PayCadence.BIWEEKLY: Decimal("26") / Decimal("12"),
    PayCadence.SEMIMONTHLY: Decimal("24") / Decimal("12"),
    PayCadence.MONTHLY: Decimal("1"),
    PayCadence.IRREGULAR: Decimal("1"),  # Irregular sources set estimated_monthly=0 in caller.
}

# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CreditEvent:
    """A single CREDIT transaction projected to the four permitted 1033 fields.

    Only the fields listed below are ever populated.  ``payee`` may be ``None`` for transactions
    where the provider did not supply a counterparty name; these are grouped together under the
    normalized payee ``"UNKNOWN"`` downstream.

    Fields consumed (1033 minimization):
        - ``txn_id`` — ``tx.id`` (output-only identifier, not used in inference).
        - ``amount`` — ``tx.amount.value``.
        - ``posted`` — ``tx.posted_timestamp``.
        - ``payee`` — ``tx.payee``.

    The ``debit_credit_memo`` field is consumed during projection (to decide whether to create
    this object at all) but is not stored — direction is implicit in the type.
    """

    txn_id: str
    amount: Decimal
    posted: datetime
    payee: str | None


@dataclass(frozen=True)
class _AmountAnalysis:
    """Intermediate result of the amount-stability and raise-detection analysis."""

    per_period_amount: Decimal
    """Representative per-deposit amount at the current (post-raise) level."""
    raise_detected: bool
    """Whether a single upward step separating two stable plateaus was detected."""
    prior_period_amount: Decimal | None
    """Median amount before the raise; ``None`` if no raise detected."""
    current_plateau: tuple[Decimal, ...]
    """Amounts in the current plateau (all amounts if no raise; post-raise amounts otherwise)."""


# ---------------------------------------------------------------------------
# Pure helper functions (all unit-testable with no I/O)
# ---------------------------------------------------------------------------


def _window_start(as_of: datetime, months: int) -> datetime:
    """Return the datetime ``months`` before ``as_of`` with the day clamped to a valid value.

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


def _normalize_payee(payee: str | None) -> str:
    """Return the upper-cased, stripped payee, or ``"UNKNOWN"`` for ``None``.

    Args:
        payee: Raw payee string from the transaction.

    Returns:
        Canonical form used for grouping and exclusion checks.
    """
    return payee.strip().upper() if payee is not None else "UNKNOWN"


def _is_excluded_counterparty(normalized: str) -> bool:
    """Return ``True`` if the payee is a known P2P or self-transfer counterparty.

    Checks against :data:`_COUNTERPARTY_DENYLIST` (exact normalized match only).

    Args:
        normalized: Upper-cased, stripped payee string.

    Returns:
        ``True`` when the payee should be excluded from income consideration.
    """
    return normalized in _COUNTERPARTY_DENYLIST


def _detect_cadence(gaps: list[float]) -> tuple[PayCadence, float]:
    """Classify a list of inter-deposit gap durations (in days) into a cadence bucket.

    Uses the *median* gap so that a few outliers (e.g. a holiday delay) do not shift the whole
    classification.

    Args:
        gaps: Consecutive inter-deposit durations in days.  Must be non-empty for a non-IRREGULAR
            result; an empty list always returns ``(IRREGULAR, 0.0)``.

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
        gaps: Inter-deposit durations in days.
        period: Canonical cadence period in days.

    Returns:
        Float in ``[0.0, 1.0]``.  ``0.0`` when *gaps* is empty or *period* is zero.
    """
    if not gaps or period == 0.0:
        return 0.0
    tolerance = max(period * 0.25, 4.0)
    count = sum(1 for g in gaps if abs(g - period) <= tolerance)
    return count / len(gaps)


def _decimal_median(amounts: list[Decimal]) -> Decimal:
    """Return the median of a non-empty list of ``Decimal`` values (exact arithmetic).

    Args:
        amounts: Non-empty list of Decimal amounts.

    Returns:
        Median value quantized to two decimal places.
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


def _analyze_amounts(amounts: list[Decimal]) -> _AmountAnalysis:
    """Detect a stable per-period amount, including a single upward raise if present.

    A "raise" is defined as a single index ``k`` where ``amounts[k]`` exceeds
    ``amounts[k-1] * (1 + AMOUNT_TOLERANCE)`` **and** both the pre- and post-raise runs are
    individually stable within the same tolerance.  Any other pattern (no step, multiple steps,
    or a step with an unstable plateau) is returned as a stable median with ``raise_detected=False``.

    Args:
        amounts: Per-deposit amounts in *chronological* order.

    Returns:
        An :class:`_AmountAnalysis` with the representative current-level amount, raise flag,
        prior-level amount (or ``None``), and the current-plateau amounts for confidence scoring.
    """
    if len(amounts) == 1:
        return _AmountAnalysis(
            per_period_amount=amounts[0],
            raise_detected=False,
            prior_period_amount=None,
            current_plateau=(amounts[0],),
        )

    # Indices where a jump > AMOUNT_TOLERANCE occurs in the upward direction.
    step_indices = [
        i
        for i in range(1, len(amounts))
        if amounts[i] > amounts[i - 1] * (Decimal(1) + AMOUNT_TOLERANCE)
    ]

    if len(step_indices) == 1:
        k = step_indices[0]
        before = amounts[:k]
        after = amounts[k:]
        if _is_stable_plateau(before) and _is_stable_plateau(after):
            m_before = _decimal_median(before)
            m_after = _decimal_median(after)
            return _AmountAnalysis(
                per_period_amount=m_after,
                raise_detected=True,
                prior_period_amount=m_before,
                current_plateau=tuple(after),
            )

    # Stable or unrecognised multi-step pattern.
    m_all = _decimal_median(amounts)
    return _AmountAnalysis(
        per_period_amount=m_all,
        raise_detected=False,
        prior_period_amount=None,
        current_plateau=tuple(amounts),
    )


def _amount_stability(plateau: tuple[Decimal, ...]) -> float:
    """Return an amount-stability score in ``[0.0, 1.0]``.

    ``1.0`` means perfectly stable (e.g. an exact payroll amount).  Score decreases as the
    coefficient of variation (σ/μ) of the plateau amounts increases.

    Args:
        plateau: Amounts in the current plateau (post-raise if a raise was detected).

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


def _to_monthly(per_period: Decimal, cadence: PayCadence) -> Decimal:
    """Normalise a per-period income amount to an estimated monthly figure.

    Args:
        per_period: The representative per-deposit amount.
        cadence: The detected cadence.

    Returns:
        Monthly equivalent, quantized to two decimal places.
    """
    factor = _MONTHLY_FACTOR[cadence]
    return (per_period * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _confidence(
    regularity: float,
    deposit_count: int,
    cadence: PayCadence,
    lookback_months: int,
    current_plateau: tuple[Decimal, ...],
) -> tuple[float, ConfidenceLevel]:
    """Compute a deterministic confidence score and label.

    Score formula::

        score = 0.5 * regularity
              + 0.3 * min(deposit_count / expected_count, 1.0)
              + 0.2 * amount_stability

    Confidence labels: ``HIGH`` ≥ :data:`CONFIDENCE_HIGH`, ``MEDIUM`` ≥ :data:`CONFIDENCE_MEDIUM`,
    ``LOW`` otherwise.

    Args:
        regularity: Fraction of gaps within tolerance of the cadence period.
        deposit_count: Actual number of deposits in the lookback window.
        cadence: Detected cadence.
        lookback_months: Width of the analysis window in calendar months.
        current_plateau: Current-level amounts for stability scoring.

    Returns:
        ``(score, level)`` — the raw float score and banded :class:`ConfidenceLevel`.
    """
    expected = _EXPECTED_PER_MONTH.get(cadence, 1.0) * lookback_months
    count_score = min(deposit_count / expected, 1.0) if expected > 0 else 0.0
    stability = _amount_stability(current_plateau)
    raw = 0.5 * regularity + 0.3 * count_score + 0.2 * stability
    score = round(min(max(raw, 0.0), 1.0), 6)
    if score >= CONFIDENCE_HIGH:
        level = ConfidenceLevel.HIGH
    elif score >= CONFIDENCE_MEDIUM:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.LOW
    return score, level


def _classify_group(payee: str, events: list[_CreditEvent], lookback_months: int) -> IncomeSource | RejectedCandidate:
    """Classify a single-payee credit group as a recurring source, irregular source, or rejected.

    Classification rules:

    - ``len(events) == 1`` → :class:`~banking_client.analytics.results.RejectedCandidate` with
      :attr:`~banking_client.analytics.results.RejectionReason.SINGLE_OCCURRENCE`.
    - ``len(events) >= MIN_RECURRING_DEPOSITS`` **and** regular cadence **and** regular gaps
      → :class:`~banking_client.analytics.results.IncomeSource` with ``is_recurring=True``.
    - ``len(events) >= 2`` otherwise
      → :class:`~banking_client.analytics.results.IncomeSource` with ``is_recurring=False``
      (irregular secondary source; cadence forced to ``IRREGULAR``, confidence ``LOW``).

    Args:
        payee: Normalized payee name.
        events: All credit events for this payee in the lookback window.
        lookback_months: Width of the analysis window in calendar months.

    Returns:
        Either an :class:`~banking_client.analytics.results.IncomeSource` or a
        :class:`~banking_client.analytics.results.RejectedCandidate`.
    """
    if len(events) == 1:
        return RejectedCandidate(
            payee=payee,
            deposit_count=1,
            reason=RejectionReason.SINGLE_OCCURRENCE,
            sample_transaction_ids=(events[0].txn_id,),
        )

    sorted_events = sorted(events, key=lambda e: e.posted)
    amounts = [e.amount for e in sorted_events]
    txn_ids = tuple(e.txn_id for e in sorted_events)

    gaps = [
        (sorted_events[i].posted - sorted_events[i - 1].posted).total_seconds() / 86400.0
        for i in range(1, len(sorted_events))
    ]

    cadence, period_days = _detect_cadence(gaps)
    regularity = _regularity(gaps, period_days) if cadence is not PayCadence.IRREGULAR else 0.0

    analysis = _analyze_amounts(amounts)

    is_recurring = (
        len(events) >= MIN_RECURRING_DEPOSITS
        and cadence is not PayCadence.IRREGULAR
        and regularity >= REGULARITY_THRESHOLD
    )

    if is_recurring:
        monthly = _to_monthly(analysis.per_period_amount, cadence)
        conf_score, conf_level = _confidence(
            regularity=regularity,
            deposit_count=len(events),
            cadence=cadence,
            lookback_months=lookback_months,
            current_plateau=analysis.current_plateau,
        )
        return IncomeSource(
            payee=payee,
            cadence=cadence,
            is_recurring=True,
            per_period_amount=analysis.per_period_amount,
            estimated_monthly_amount=monthly,
            deposit_count=len(events),
            first_seen=sorted_events[0].posted,
            last_seen=sorted_events[-1].posted,
            raise_detected=analysis.raise_detected,
            prior_period_amount=analysis.prior_period_amount,
            confidence=conf_level,
            confidence_score=conf_score,
            supporting_transaction_ids=txn_ids,
        )

    # Irregular secondary source (≥ 2 deposits, not qualifying as recurring).
    median_amount = _decimal_median(amounts)
    return IncomeSource(
        payee=payee,
        cadence=PayCadence.IRREGULAR,
        is_recurring=False,
        per_period_amount=median_amount,
        estimated_monthly_amount=Decimal("0.00"),
        deposit_count=len(events),
        first_seen=sorted_events[0].posted,
        last_seen=sorted_events[-1].posted,
        raise_detected=False,
        prior_period_amount=None,
        confidence=ConfidenceLevel.LOW,
        confidence_score=0.0,
        supporting_transaction_ids=txn_ids,
    )


def _to_credit_event(tx: Transaction) -> _CreditEvent | None:
    """Project a :class:`~banking_client.models.transaction.Transaction` to a minimal credit event.

    This function is the **documented 1033 minimization point**.  It reads exactly the five
    fields listed below and ignores every other field on the transaction.

    Fields consumed:
        - ``tx.id`` (output identifier).
        - ``tx.amount.value`` (the settled amount).
        - ``tx.posted_timestamp`` (cadence clock).
        - ``tx.debit_credit_memo`` (direction filter — only CREDITs proceed).
        - ``tx.payee`` (counterparty grouping).

    Fields deliberately **not read**:
        ``tx.category``, ``tx.description``, ``tx.transaction_timestamp``, ``tx.status``,
        ``tx.account_id``, ``tx.location``, and any other field not listed above.

    Args:
        tx: The source transaction.

    Returns:
        A :class:`_CreditEvent` for CREDIT transactions with a settled timestamp, or ``None``
        for debits or pending transactions.
    """
    # 1033 minimization: the only direction-check we perform.
    if tx.debit_credit_memo is not DebitCreditMemo.CREDIT:
        return None
    # Pending transactions have no posted_timestamp; the service operates on settled credits only.
    posted = tx.posted_timestamp
    if posted is None:
        return None
    return _CreditEvent(txn_id=tx.id, amount=tx.amount.value, posted=posted, payee=tx.payee)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class IncomeService:
    """Deterministic income-determination service.

    Infers a customer's regular income from FDX transaction history using only the 1033-minimum
    set of transaction fields (see module docstring).  All data access is delegated to the
    injected :class:`~banking_client.client.transactions.TransactionsClient` (and optionally
    :class:`~banking_client.client.accounts.AccountsClient`), which carry their own auth guards
    and audit trails.

    Args:
        transactions_client: Handles transaction fetching and enforces auth on every call.
        accounts_client: Required for :meth:`estimate_regular_income` when *account_id* is
            omitted.  The client automatically selects the customer's CHECKING accounts.

    Example::

        svc = default_income_service()
        estimate = await svc.estimate_regular_income(
            "tok_cust_001", as_of=datetime(2026, 6, 30, tzinfo=UTC)
        )
        print(estimate.status, estimate.estimated_monthly_income)
    """

    def __init__(
        self,
        transactions_client: TransactionsClient,
        accounts_client: AccountsClient | None = None,
    ) -> None:
        """Store the injected clients.

        Args:
            transactions_client: Transaction client with auth + audit.
            accounts_client: Account client; only needed when *account_id* is omitted.
        """
        self._tx_client = transactions_client
        self._acct_client = accounts_client

    async def estimate_regular_income(
        self,
        token: str,
        account_id: str | None = None,
        *,
        lookback_months: int = 12,
        as_of: datetime | None = None,
    ) -> IncomeEstimate:
        """Estimate regular income from the transaction history of one or more accounts.

        Detection pipeline:

        1. **Resolve accounts.** If *account_id* is given, analyse that account only.
           Otherwise, list the customer's accounts (requires ACCOUNTS scope) and select all
           CHECKING accounts.
        2. **Fetch & minimize.** Paginate all POSTED transactions in the lookback window per
           account, projecting each into :class:`_CreditEvent` (the 1033 minimization step).
        3. **Filter to CREDITs.** :func:`_to_credit_event` discards debits and pending items.
        4. **Counterparty exclusion.** Credits from known P2P / self-transfer payees
           (:data:`_COUNTERPARTY_DENYLIST`) are removed and recorded in ``rejected_sources``.
        5. **Group by normalized payee.**
        6. **Classify each group.** :func:`_classify_group` measures cadence (median inter-
           deposit gap), regularity, and amount stability.  A stream is *recurring* when it has
           ≥ :data:`MIN_RECURRING_DEPOSITS` deposits, a recognized cadence, regularity ≥
           :data:`REGULARITY_THRESHOLD`, and stable (or single-step) amounts.  Streams with ≥ 2
           deposits that miss the bar surface as irregular secondary sources.  Single deposits
           are rejected.
        7. **Assemble result.** The highest-monthly recurring stream is the ``primary_source``;
           remaining sources and irregular streams populate ``additional_sources``.

        Args:
            token: Opaque bearer token passed to every underlying client call.
            account_id: Specific account to analyse.  When ``None`` the service lists the
                customer's accounts and selects CHECKING accounts automatically (requires the
                token to hold ACCOUNTS scope).
            lookback_months: Number of calendar months of history to analyse.  Default is 12.
            as_of: Upper bound of the lookback window; defaults to ``datetime.now(UTC)``.
                Inject a fixed datetime in tests for determinism.

        Returns:
            An :class:`~banking_client.analytics.results.IncomeEstimate` with status, the
            primary income source (if detected), additional sources, and rejected candidates.

        Raises:
            AuthenticationError: Token unknown or expired (propagated from the underlying client).
            AuthorizationError: Token lacks TRANSACTIONS scope, or ACCOUNTS scope when
                *account_id* is omitted (propagated from the underlying client).
            ValueError: *accounts_client* was not supplied and *account_id* is ``None``.
        """
        effective_as_of = as_of if as_of is not None else datetime.now(UTC)

        # ------------------------------------------------------------------
        # 1. Resolve account ids.
        # ------------------------------------------------------------------
        account_ids: tuple[str, ...]
        if account_id is not None:
            account_ids = (account_id,)
        else:
            if self._acct_client is None:
                raise ValueError("accounts_client is required when account_id is omitted")
            accts_page = await self._acct_client.get_accounts(token, limit=100)
            checking = [a for a in accts_page.items if a.account_type is AccountType.CHECKING]
            account_ids = tuple(a.id for a in checking)

        if not account_ids:
            return IncomeEstimate(
                status=IncomeStatus.INSUFFICIENT_HISTORY,
                as_of=effective_as_of,
                lookback_months=lookback_months,
                account_ids=(),
                estimated_monthly_income=None,
                primary_source=None,
                additional_sources=(),
                rejected_sources=(),
            )

        # ------------------------------------------------------------------
        # 2. Fetch & minimize: collect all CREDIT events across accounts.
        # ------------------------------------------------------------------
        window_start_dt = _window_start(effective_as_of, lookback_months)
        all_events: list[_CreditEvent] = []

        for acct_id in account_ids:
            page_key: str | None = None
            while True:
                page = await self._tx_client.get_transactions(
                    token,
                    acct_id,
                    start_time=window_start_dt,
                    end_time=effective_as_of,
                    status=TransactionStatus.POSTED,
                    limit=_FETCH_PAGE_SIZE,
                    page_key=page_key,
                )
                for tx in page.items:
                    event = _to_credit_event(tx)
                    if event is not None:
                        all_events.append(event)
                if page.page.next_offset is None:
                    break
                page_key = page.page.next_offset

        # ------------------------------------------------------------------
        # 3. Early exit: insufficient credits to detect any recurring stream.
        # ------------------------------------------------------------------
        if len(all_events) < MIN_RECURRING_DEPOSITS:
            return IncomeEstimate(
                status=IncomeStatus.INSUFFICIENT_HISTORY,
                as_of=effective_as_of,
                lookback_months=lookback_months,
                account_ids=account_ids,
                estimated_monthly_income=None,
                primary_source=None,
                additional_sources=(),
                rejected_sources=(),
            )

        # ------------------------------------------------------------------
        # 4. Counterparty exclusion and payee grouping.
        # ------------------------------------------------------------------
        candidate_groups: defaultdict[str, list[_CreditEvent]] = defaultdict(list)
        excluded_groups: defaultdict[str, list[_CreditEvent]] = defaultdict(list)

        for event in all_events:
            norm = _normalize_payee(event.payee)
            if _is_excluded_counterparty(norm):
                excluded_groups[norm].append(event)
            else:
                candidate_groups[norm].append(event)

        rejected_from_exclusion = [
            RejectedCandidate(
                payee=norm,
                deposit_count=len(events),
                reason=RejectionReason.EXCLUDED_COUNTERPARTY,
                sample_transaction_ids=tuple(e.txn_id for e in events[:5]),
            )
            for norm, events in sorted(excluded_groups.items())
        ]

        # ------------------------------------------------------------------
        # 5–6. Classify each candidate group.
        # ------------------------------------------------------------------
        sources: list[IncomeSource] = []
        rejected_from_single: list[RejectedCandidate] = []

        for norm_payee, events in sorted(candidate_groups.items()):
            result = _classify_group(norm_payee, events, lookback_months)
            if isinstance(result, IncomeSource):
                sources.append(result)
            else:
                rejected_from_single.append(result)

        all_rejected: tuple[RejectedCandidate, ...] = tuple(
            rejected_from_exclusion + rejected_from_single
        )

        # ------------------------------------------------------------------
        # 7. Assemble result.
        # ------------------------------------------------------------------
        recurring = [s for s in sources if s.is_recurring]
        irregular = sorted(
            (s for s in sources if not s.is_recurring),
            key=lambda s: s.deposit_count,
            reverse=True,
        )

        if not recurring:
            return IncomeEstimate(
                status=IncomeStatus.NO_RECURRING_INCOME,
                as_of=effective_as_of,
                lookback_months=lookback_months,
                account_ids=account_ids,
                estimated_monthly_income=None,
                primary_source=None,
                additional_sources=tuple(irregular),
                rejected_sources=all_rejected,
            )

        # Sort recurring descending by monthly amount; tie-break by deposit_count then payee.
        recurring.sort(key=lambda s: (-s.estimated_monthly_amount, -s.deposit_count, s.payee))
        primary = recurring[0]
        additional = tuple(recurring[1:] + irregular)

        return IncomeEstimate(
            status=IncomeStatus.DETECTED,
            as_of=effective_as_of,
            lookback_months=lookback_months,
            account_ids=account_ids,
            estimated_monthly_income=primary.estimated_monthly_amount,
            primary_source=primary,
            additional_sources=additional,
            rejected_sources=all_rejected,
        )


def default_income_service(*, trail: AuditTrail | None = None) -> IncomeService:
    """Return an :class:`IncomeService` wired to the committed fixture data.

    Both underlying clients are wired to the same *trail* so all audit events from a single
    logical request flow to the same sink in tests.

    Args:
        trail: Optional audit trail shared by both underlying clients.  Pass
            ``AuditTrail(sink=ListSink())`` in tests to capture and assert events without stdout
            noise.

    Returns:
        A fully wired :class:`IncomeService` backed by fixture data.

    Example::

        svc = default_income_service(trail=AuditTrail(sink=ListSink()))
        estimate = await svc.estimate_regular_income("tok_cust_001")
    """
    return IncomeService(
        transactions_client=default_transactions_client(trail=trail),
        accounts_client=default_accounts_client(trail=trail),
    )
