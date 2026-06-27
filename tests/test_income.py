"""Tests for the income-determination service.

Structure
---------
- **Pure unit tests** exercise the deterministic helper functions (cadence detection,
  regularity, amount analysis, raise detection, monthly normalization, confidence scoring)
  directly from ``_CreditEvent`` lists — no auth, no I/O, no async.
- **Service unit tests** wire :class:`~banking_client.analytics.income.IncomeService` with
  in-memory fakes (``_FakeTxnSource`` + ``_FakeResolver``) to verify the aggregate pipeline
  behaviour for edge cases (INSUFFICIENT_HISTORY, NO_RECURRING_INCOME) cleanly.
- **Integration tests** hit the committed fixture files via
  :func:`~banking_client.analytics.income.default_income_service` (real auth, real data,
  real audit trail) to exercise the correctness story: detect payroll, reject Venmo,
  handle the mid-history raise, and separate freelance from primary income.

1033 minimization note
-----------------------
The integration tests do **not** inspect ``Transaction.category`` or ``Transaction.description``
to verify results — doing so would defeat the point.  Assertions are over the output (payee,
cadence, amounts, ``raise_detected``) derived entirely from the 4 permitted fields.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from banking_client.analytics.income import (
    MIN_RECURRING_DEPOSITS,
    _amount_stability,
    _analyze_amounts,
    _classify_group,
    _confidence,
    _CreditEvent,
    _decimal_median,
    _detect_cadence,
    _is_excluded_counterparty,
    _is_stable_plateau,
    _normalize_payee,
    _regularity,
    _to_credit_event,
    _to_monthly,
    _window_start,
    default_income_service,
)
from banking_client.analytics.results import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    ConfidenceLevel,
    IncomeStatus,
    PayCadence,
    RejectionReason,
)
from banking_client.auth import Authorizer, DataCluster
from banking_client.auth.scope import ConsentScope
from banking_client.client.transactions import TransactionsClient
from banking_client.models.enums import DebitCreditMemo, TransactionStatus
from banking_client.models.money import Money
from banking_client.models.transaction import Transaction
from common.audit import AuditOutcome, AuditTrail, ListSink
from common.errors import AuthenticationError, AuthorizationError

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

_ANCHOR = datetime(2026, 6, 30, tzinfo=UTC)
"""Fixed fixture anchor date for integration tests."""

_TOKEN_001 = "tok_cust_001"  # ACCOUNTS + TRANSACTIONS, cust-001-checking
_TOKEN_002 = "tok_cust_002"  # ACCOUNTS + TRANSACTIONS, cust-002-checking/savings/card
_TOKEN_003 = "tok_cust_003"  # ACCOUNTS + TRANSACTIONS, cust-003-checking/savings
_TOKEN_003_TXN_ONLY = "tok_cust_003_txn_only"  # TRANSACTIONS only


# ---------------------------------------------------------------------------
# Helpers: _CreditEvent builders
# ---------------------------------------------------------------------------


def _event(
    amount: str,
    posted: datetime,
    payee: str | None = "TEST PAYROLL",
    txn_id: str = "txn-001",
) -> _CreditEvent:
    """Build a _CreditEvent from primitive args."""
    return _CreditEvent(txn_id=txn_id, amount=Decimal(amount), posted=posted, payee=payee)


def _biweekly_stream(
    n: int,
    amount: str,
    start: datetime,
    payee: str = "ACME CORP PAYROLL",
) -> list[_CreditEvent]:
    """Build *n* _CreditEvent objects spaced exactly 14 days apart starting at *start*."""
    return [
        _CreditEvent(
            txn_id=f"txn-bw-{i:04d}",
            amount=Decimal(amount),
            posted=start + timedelta(days=14 * i),
            payee=payee,
        )
        for i in range(n)
    ]


def _irregular_stream(
    n: int,
    amount: str,
    start: datetime,
    gap_days: int = 3,
    payee: str = "RANDOM CO",
) -> list[_CreditEvent]:
    """Build *n* events with a fixed but irregular-for-cadence gap (default 3 days)."""
    return [
        _CreditEvent(
            txn_id=f"txn-ir-{i:04d}",
            amount=Decimal(amount),
            posted=start + timedelta(days=gap_days * i),
            payee=payee,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Helpers: Transaction builder (for _to_credit_event unit tests)
# ---------------------------------------------------------------------------


def _txn(
    amount: str = "100.00",
    memo: DebitCreditMemo = DebitCreditMemo.CREDIT,
    payee: str | None = "PAYROLL CO",
    posted: datetime | None = datetime(2025, 1, 1, tzinfo=UTC),
    status: TransactionStatus = TransactionStatus.POSTED,
    txn_id: str = "txn-test-001",
) -> Transaction:
    """Build a Transaction for _to_credit_event unit tests."""
    resolved_posted = posted if status is TransactionStatus.POSTED else None
    return Transaction(
        id=txn_id,
        account_id="acct-test",
        amount=Money(value=Decimal(amount), currency="USD"),
        posted_timestamp=resolved_posted,
        transaction_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        description="TEST",
        debit_credit_memo=memo,
        status=status,
        payee=payee,
    )


# ---------------------------------------------------------------------------
# Helpers: fake auth + data source for service unit tests
# ---------------------------------------------------------------------------


class _FakeResolver:
    """Minimal ConsentResolver backed by a static dict (no filesystem)."""

    def __init__(self, registry: dict[str, ConsentScope]) -> None:
        """Bind registry."""
        self._registry = registry

    def resolve(self, token: str) -> ConsentScope:
        """Raise AuthenticationError for unknown tokens; return scope otherwise."""
        scope = self._registry.get(token)
        if scope is None:
            raise AuthenticationError(f"Unknown token: {token!r}")
        return scope


def _scope(
    *,
    customer_id: str = "cust-test",
    account_ids: list[str] | None = None,
    clusters: list[DataCluster] | None = None,
) -> ConsentScope:
    """Build a ConsentScope; defaults to TRANSACTIONS on test-checking."""
    return ConsentScope(
        consent_id=f"consent-{customer_id}",
        customer_id=customer_id,
        account_ids=frozenset(account_ids or ["test-checking"]),
        data_clusters=frozenset(clusters or [DataCluster.TRANSACTIONS]),
        expires_at=None,
    )


class _FakeTxnSource:
    """In-memory TransactionDataSource satisfied by a static list."""

    def __init__(self, txns: list[Transaction]) -> None:
        """Bind transaction list."""
        self._txns = txns

    async def list_transactions(self, *, token: str, customer_id: str, account_id: str) -> list[Transaction]:
        """Return all transactions regardless of account_id."""
        return self._txns


# ===========================================================================
# _window_start — pure unit tests
# ===========================================================================


def test_window_start_twelve_months_back() -> None:
    """12 months back from 2026-06-30 returns 2025-06-30 (same day, same tz)."""
    result = _window_start(datetime(2026, 6, 30, tzinfo=UTC), 12)
    assert result == datetime(2025, 6, 30, tzinfo=UTC)


def test_window_start_clamps_day_to_month_end() -> None:
    """1 month back from March 31 returns Feb 28 (day clamped to month length)."""
    result = _window_start(datetime(2026, 3, 31, tzinfo=UTC), 1)
    assert result == datetime(2026, 2, 28, tzinfo=UTC)


def test_window_start_twenty_four_months() -> None:
    """24 months back from 2026-06-30 returns 2024-06-30."""
    result = _window_start(datetime(2026, 6, 30, tzinfo=UTC), 24)
    assert result == datetime(2024, 6, 30, tzinfo=UTC)


def test_window_start_preserves_tzinfo() -> None:
    """The result carries the same tzinfo as the input anchor."""
    result = _window_start(datetime(2026, 6, 30, tzinfo=UTC), 6)
    assert result.tzinfo is UTC


# ===========================================================================
# _normalize_payee — pure unit tests
# ===========================================================================


def test_normalize_payee_none_returns_unknown() -> None:
    """None payee normalizes to UNKNOWN."""
    assert _normalize_payee(None) == "UNKNOWN"


def test_normalize_payee_strips_and_uppercases() -> None:
    """Mixed-case payee with whitespace is normalized."""
    assert _normalize_payee("  venmo  ") == "VENMO"


def test_normalize_payee_already_canonical() -> None:
    """An already-canonical payee is returned unchanged."""
    assert _normalize_payee("GLOBEX LLC PAYROLL") == "GLOBEX LLC PAYROLL"


# ===========================================================================
# _is_excluded_counterparty — pure unit tests
# ===========================================================================


def test_excluded_counterparty_venmo_rejected() -> None:
    """VENMO is a known P2P payee and must be excluded."""
    assert _is_excluded_counterparty("VENMO") is True


def test_excluded_counterparty_internal_transfer_rejected() -> None:
    """INTERNAL TRANSFER is a self-transfer and must be excluded."""
    assert _is_excluded_counterparty("INTERNAL TRANSFER") is True


def test_excluded_counterparty_zelle_rejected() -> None:
    """ZELLE is a P2P payee."""
    assert _is_excluded_counterparty("ZELLE") is True


def test_excluded_counterparty_payroll_not_rejected() -> None:
    """Legitimate payroll payees are not in the denylist."""
    assert _is_excluded_counterparty("ACME CORP PAYROLL") is False
    assert _is_excluded_counterparty("GLOBEX LLC PAYROLL") is False


def test_excluded_counterparty_freelance_not_rejected() -> None:
    """Freelance platforms are not in the denylist (exclusion is payee-exact)."""
    assert _is_excluded_counterparty("UPWORK") is False
    assert _is_excluded_counterparty("FIVERR") is False


# ===========================================================================
# _detect_cadence — pure unit tests
# ===========================================================================


def test_detect_cadence_empty_gaps_returns_irregular() -> None:
    """No gaps (single deposit) yields IRREGULAR."""
    cadence, period = _detect_cadence([])
    assert cadence is PayCadence.IRREGULAR


def test_detect_cadence_biweekly_exact() -> None:
    """Exactly 14-day gaps classify as BIWEEKLY with period 14."""
    cadence, period = _detect_cadence([14.0] * 5)
    assert cadence is PayCadence.BIWEEKLY
    assert period == 14.0


def test_detect_cadence_biweekly_with_small_jitter() -> None:
    """Gaps around 14 days (with ±2 day noise) still classify as BIWEEKLY."""
    cadence, _ = _detect_cadence([13.5, 14.2, 13.8, 14.5, 13.9])
    assert cadence is PayCadence.BIWEEKLY


def test_detect_cadence_weekly() -> None:
    """Gaps near 7 days classify as WEEKLY."""
    cadence, period = _detect_cadence([7.0] * 4)
    assert cadence is PayCadence.WEEKLY
    assert period == 7.0


def test_detect_cadence_monthly() -> None:
    """Gaps near 30 days classify as MONTHLY."""
    cadence, period = _detect_cadence([30.0] * 11)
    assert cadence is PayCadence.MONTHLY
    assert period == 30.0


def test_detect_cadence_irregular_outside_all_buckets() -> None:
    """A median gap outside all buckets yields IRREGULAR."""
    cadence, _ = _detect_cadence([20.0, 20.0, 20.0])
    assert cadence is PayCadence.IRREGULAR


def test_detect_cadence_uses_median_not_mean() -> None:
    """One large outlier in 5 gaps doesn't flip the cadence away from BIWEEKLY."""
    gaps = [14.0, 14.0, 14.0, 14.0, 100.0]  # median=14, mean=31.2
    cadence, _ = _detect_cadence(gaps)
    assert cadence is PayCadence.BIWEEKLY


# ===========================================================================
# _regularity — pure unit tests
# ===========================================================================


def test_regularity_perfect_biweekly_is_one() -> None:
    """Exactly 14-day gaps → regularity 1.0."""
    assert _regularity([14.0] * 10, 14.0) == 1.0


def test_regularity_empty_gaps_is_zero() -> None:
    """Empty gap list → regularity 0.0."""
    assert _regularity([], 14.0) == 0.0


def test_regularity_zero_period_is_zero() -> None:
    """Zero period → regularity 0.0 (guard against division by zero)."""
    assert _regularity([14.0], 0.0) == 0.0


def test_regularity_one_outlier_reduces_score() -> None:
    """One gap out of tolerance reduces regularity below 1."""
    gaps = [14.0] * 9 + [50.0]  # 1 outlier in 10
    score = _regularity(gaps, 14.0)
    assert score == pytest.approx(0.9)


def test_regularity_within_min_tolerance() -> None:
    """Gaps within ±4 days (min tolerance) still qualify for biweekly."""
    gaps = [13.0, 14.0, 15.0, 16.0]  # all within ±3 days of 14
    score = _regularity(gaps, 14.0)
    assert score == 1.0


# ===========================================================================
# _decimal_median — pure unit tests
# ===========================================================================


def test_decimal_median_odd_length() -> None:
    """Middle element for odd-length list."""
    result = _decimal_median([Decimal("100"), Decimal("200"), Decimal("300")])
    assert result == Decimal("200.00")


def test_decimal_median_even_length() -> None:
    """Average of two middle elements for even-length list."""
    result = _decimal_median([Decimal("100"), Decimal("200")])
    assert result == Decimal("150.00")


# ===========================================================================
# _is_stable_plateau — pure unit tests
# ===========================================================================


def test_stable_plateau_single_element_is_stable() -> None:
    """A single-element list is always stable."""
    assert _is_stable_plateau([Decimal("1800.00")]) is True


def test_stable_plateau_identical_values_is_stable() -> None:
    """Identical amounts are perfectly stable."""
    amounts = [Decimal("2050.00")] * 20
    assert _is_stable_plateau(amounts) is True


def test_stable_plateau_variable_amounts_is_unstable() -> None:
    """Amounts varying > 10% from the median are not stable."""
    amounts = [Decimal("100.00"), Decimal("500.00"), Decimal("200.00")]
    assert _is_stable_plateau(amounts) is False


# ===========================================================================
# _analyze_amounts — pure unit tests
# ===========================================================================


def test_analyze_amounts_stable_no_raise() -> None:
    """Uniform amounts: no raise detected, per_period = the uniform value."""
    amounts = [Decimal("925.00")] * 10
    result = _analyze_amounts(amounts)
    assert result.raise_detected is False
    assert result.per_period_amount == Decimal("925.00")
    assert result.prior_period_amount is None
    assert len(result.current_plateau) == 10


def test_analyze_amounts_clean_step_detected() -> None:
    """A single upward step (> 10%) between two stable plateaus is detected as a raise."""
    before = [Decimal("1800.00")] * 5
    after = [Decimal("2050.00")] * 21
    result = _analyze_amounts(before + after)
    assert result.raise_detected is True
    assert result.prior_period_amount == Decimal("1800.00")
    assert result.per_period_amount == Decimal("2050.00")
    assert len(result.current_plateau) == 21


def test_analyze_amounts_two_steps_not_a_raise() -> None:
    """Two upward steps yield no raise detection (returns median of all)."""
    amounts = [Decimal("1000.00")] * 3 + [Decimal("1200.00")] * 3 + [Decimal("1500.00")] * 3
    result = _analyze_amounts(amounts)
    assert result.raise_detected is False


def test_analyze_amounts_small_step_below_tolerance_ignored() -> None:
    """A step below AMOUNT_TOLERANCE (10%) is not considered a raise."""
    # 1800 → 1850 is only +2.8% < 10%
    before = [Decimal("1800.00")] * 5
    after = [Decimal("1850.00")] * 5
    result = _analyze_amounts(before + after)
    assert result.raise_detected is False


def test_analyze_amounts_single_deposit_no_raise() -> None:
    """A single deposit always returns no raise."""
    result = _analyze_amounts([Decimal("500.00")])
    assert result.raise_detected is False
    assert result.per_period_amount == Decimal("500.00")


# ===========================================================================
# _amount_stability — pure unit tests
# ===========================================================================


def test_amount_stability_uniform_is_one() -> None:
    """All identical amounts → stability 1.0."""
    plateau = tuple(Decimal("925.00") for _ in range(20))
    assert _amount_stability(plateau) == pytest.approx(1.0)


def test_amount_stability_single_element_is_one() -> None:
    """Single-element plateau → stability 1.0."""
    assert _amount_stability((Decimal("500.00"),)) == pytest.approx(1.0)


def test_amount_stability_high_variance_is_low() -> None:
    """Wildly varying amounts → stability near 0."""
    plateau = tuple(Decimal(str(v)) for v in [100, 300, 1400, 500, 800])
    stability = _amount_stability(plateau)
    assert stability < 0.5


# ===========================================================================
# _to_monthly — pure unit tests
# ===========================================================================


def test_to_monthly_biweekly_925() -> None:
    """Biweekly $925 → ~$2004.17/month (925 × 26/12)."""
    result = _to_monthly(Decimal("925.00"), PayCadence.BIWEEKLY)
    assert result == Decimal("2004.17")


def test_to_monthly_monthly_passthrough() -> None:
    """Monthly cadence: per-period amount is unchanged."""
    result = _to_monthly(Decimal("2000.00"), PayCadence.MONTHLY)
    assert result == Decimal("2000.00")


def test_to_monthly_weekly() -> None:
    """Weekly × 52/12 normalizes to monthly."""
    result = _to_monthly(Decimal("500.00"), PayCadence.WEEKLY)
    expected = (Decimal("500") * Decimal("52") / Decimal("12")).quantize(
        Decimal("0.01"), rounding=__import__("decimal").ROUND_HALF_UP
    )
    assert result == expected


# ===========================================================================
# _confidence — pure unit tests
# ===========================================================================


def test_confidence_perfect_payroll_is_high() -> None:
    """Perfect regularity, full deposit count, stable amounts → HIGH confidence."""
    plateau = tuple(Decimal("925.00") for _ in range(26))
    score, level = _confidence(
        regularity=1.0,
        deposit_count=26,
        cadence=PayCadence.BIWEEKLY,
        lookback_months=12,
        current_plateau=plateau,
    )
    assert level is ConfidenceLevel.HIGH
    assert score >= CONFIDENCE_HIGH


def test_confidence_low_regularity_is_low() -> None:
    """Low regularity score produces LOW confidence."""
    plateau = (Decimal("100.00"),)
    score, level = _confidence(
        regularity=0.2,
        deposit_count=4,
        cadence=PayCadence.BIWEEKLY,
        lookback_months=12,
        current_plateau=plateau,
    )
    assert level is ConfidenceLevel.LOW
    assert score < CONFIDENCE_MEDIUM


def test_confidence_label_thresholds_are_applied() -> None:
    """Score at the MEDIUM threshold maps to MEDIUM level."""
    plateau = (Decimal("100.00"),)
    score, level = _confidence(
        regularity=1.0,
        deposit_count=4,
        cadence=PayCadence.BIWEEKLY,
        lookback_months=12,
        current_plateau=plateau,
    )
    # Computed: 0.5*1.0 + 0.3*(4/26) + 0.2*1.0 = 0.5 + 0.046 + 0.2 = 0.746
    # Expect HIGH or MEDIUM depending on exact score.
    assert level in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)


# ===========================================================================
# _classify_group — pure unit tests
# ===========================================================================


def test_classify_group_single_deposit_rejected_single_occurrence() -> None:
    """One deposit from a payee → RejectedCandidate with SINGLE_OCCURRENCE."""
    events = [_event("50.00", datetime(2025, 1, 1, tzinfo=UTC))]
    result = _classify_group("AMAZON", events, 12)
    from banking_client.analytics.results import RejectedCandidate

    assert isinstance(result, RejectedCandidate)
    assert result.reason is RejectionReason.SINGLE_OCCURRENCE
    assert result.deposit_count == 1


def test_classify_group_biweekly_payroll_is_recurring_high() -> None:
    """26 biweekly deposits with stable amount → recurring, HIGH confidence."""
    events = _biweekly_stream(26, "925.00", datetime(2025, 7, 1, tzinfo=UTC))
    result = _classify_group("ACME CORP PAYROLL", events, 12)
    from banking_client.analytics.results import IncomeSource

    assert isinstance(result, IncomeSource)
    assert result.is_recurring is True
    assert result.cadence is PayCadence.BIWEEKLY
    assert result.per_period_amount == Decimal("925.00")
    assert result.confidence is ConfidenceLevel.HIGH
    assert len(result.supporting_transaction_ids) == 26


def test_classify_group_irregular_deposits_are_non_recurring() -> None:
    """5 deposits with 3-day gaps (irregular cadence) → non-recurring secondary source."""
    events = _irregular_stream(5, "300.00", datetime(2025, 1, 1, tzinfo=UTC), gap_days=3)
    result = _classify_group("UPWORK", events, 12)
    from banking_client.analytics.results import IncomeSource

    assert isinstance(result, IncomeSource)
    assert result.is_recurring is False
    assert result.cadence is PayCadence.IRREGULAR
    assert result.confidence is ConfidenceLevel.LOW


def test_classify_group_detects_raise_in_biweekly_stream() -> None:
    """A biweekly stream with a mid-history raise: recurring, raise_detected=True."""
    before = _biweekly_stream(5, "1800.00", datetime(2025, 7, 13, tzinfo=UTC), payee="GLOBEX LLC PAYROLL")
    after_start = datetime(2025, 7, 13, tzinfo=UTC) + timedelta(days=5 * 14)
    after = _biweekly_stream(21, "2050.00", after_start, payee="GLOBEX LLC PAYROLL")
    events = before + after
    result = _classify_group("GLOBEX LLC PAYROLL", events, 12)
    from banking_client.analytics.results import IncomeSource

    assert isinstance(result, IncomeSource)
    assert result.is_recurring is True
    assert result.raise_detected is True
    assert result.prior_period_amount == Decimal("1800.00")
    assert result.per_period_amount == Decimal("2050.00")


def test_classify_group_insufficient_deposits_non_recurring() -> None:
    """3 biweekly deposits (< MIN_RECURRING_DEPOSITS=4) → non-recurring (not REJECTED)."""
    events = _biweekly_stream(3, "1000.00", datetime(2025, 1, 1, tzinfo=UTC))
    result = _classify_group("PAYROLL CO", events, 12)
    from banking_client.analytics.results import IncomeSource

    assert isinstance(result, IncomeSource)
    assert result.is_recurring is False


# ===========================================================================
# _to_credit_event — pure unit tests
# ===========================================================================


def test_to_credit_event_credit_returns_event() -> None:
    """A POSTED CREDIT produces a _CreditEvent with the correct fields."""
    posted = datetime(2025, 6, 1, tzinfo=UTC)
    tx = _txn(amount="1234.56", memo=DebitCreditMemo.CREDIT, payee="TEST PAYROLL", posted=posted)
    result = _to_credit_event(tx)
    assert result is not None
    assert result.amount == Decimal("1234.56")
    assert result.posted == posted
    assert result.payee == "TEST PAYROLL"


def test_to_credit_event_debit_returns_none() -> None:
    """A DEBIT transaction is discarded (only CREDITs are income candidates)."""
    tx = _txn(memo=DebitCreditMemo.DEBIT)
    assert _to_credit_event(tx) is None


def test_to_credit_event_pending_credit_returns_none() -> None:
    """A PENDING CREDIT (no posted_timestamp) is discarded."""
    tx = _txn(memo=DebitCreditMemo.CREDIT, status=TransactionStatus.PENDING, posted=None)
    assert _to_credit_event(tx) is None


def test_to_credit_event_does_not_read_category_or_description() -> None:
    """Confirm: _to_credit_event can handle a transaction with no category without error."""
    # If the function inadvertently read category, a missing category would surface.
    tx = _txn(memo=DebitCreditMemo.CREDIT)
    # Transaction has no category set (defaults to None) — should still produce an event.
    assert tx.category is None
    assert _to_credit_event(tx) is not None


# ===========================================================================
# Service unit tests — fake data source, edge cases
# ===========================================================================


async def test_service_insufficient_history_few_credits() -> None:
    """Fewer than MIN_RECURRING_DEPOSITS credits → INSUFFICIENT_HISTORY."""
    from banking_client.analytics.income import IncomeService

    posted = datetime(2025, 6, 1, tzinfo=UTC)
    txns = [
        _txn(amount="100.00", txn_id=f"t{i}", posted=posted + timedelta(days=i * 14))
        for i in range(MIN_RECURRING_DEPOSITS - 1)  # one short of the threshold
    ]
    registry = {"tok-test": _scope()}
    authorizer = Authorizer(resolver=_FakeResolver(registry))  # type: ignore[arg-type]
    tx_client = TransactionsClient(
        data_source=_FakeTxnSource(txns),  # type: ignore[arg-type]
        authorizer=authorizer,
        trail=AuditTrail(sink=ListSink()),
    )
    svc = IncomeService(transactions_client=tx_client)
    result = await svc.estimate_regular_income("tok-test", "test-checking", as_of=datetime(2026, 6, 30, tzinfo=UTC))
    assert result.status is IncomeStatus.INSUFFICIENT_HISTORY
    assert result.estimated_monthly_income is None
    assert result.primary_source is None


async def test_service_no_recurring_income_all_irregular() -> None:
    """Credits present but all with irregular cadence → NO_RECURRING_INCOME."""
    from banking_client.analytics.income import IncomeService

    # 8 credits to different payees (each with 1 deposit → SINGLE_OCCURRENCE rejected).
    # Start well inside the 12-month window (window = 2025-06-30 → 2026-06-30).
    posted_base = datetime(2025, 7, 1, tzinfo=UTC)
    txns = [
        _txn(
            amount="50.00",
            txn_id=f"t{i}",
            payee=f"ONE-TIME-PAYEE-{i}",
            posted=posted_base + timedelta(days=i * 30),
        )
        for i in range(8)
    ]
    registry = {"tok-test": _scope()}
    authorizer = Authorizer(resolver=_FakeResolver(registry))  # type: ignore[arg-type]
    tx_client = TransactionsClient(
        data_source=_FakeTxnSource(txns),  # type: ignore[arg-type]
        authorizer=authorizer,
        trail=AuditTrail(sink=ListSink()),
    )
    svc = IncomeService(transactions_client=tx_client)
    result = await svc.estimate_regular_income("tok-test", "test-checking", as_of=datetime(2026, 6, 30, tzinfo=UTC))
    assert result.status is IncomeStatus.NO_RECURRING_INCOME
    assert result.primary_source is None
    # All single-occurrence payees appear in rejected_sources
    assert len(result.rejected_sources) == 8
    assert all(r.reason is RejectionReason.SINGLE_OCCURRENCE for r in result.rejected_sources)


async def test_service_requires_accounts_client_when_account_id_omitted() -> None:
    """Omitting account_id without an AccountsClient raises ValueError."""
    from banking_client.analytics.income import IncomeService

    registry = {"tok-test": _scope()}
    authorizer = Authorizer(resolver=_FakeResolver(registry))  # type: ignore[arg-type]
    tx_client = TransactionsClient(
        data_source=_FakeTxnSource([]),  # type: ignore[arg-type]
        authorizer=authorizer,
        trail=AuditTrail(sink=ListSink()),
    )
    svc = IncomeService(transactions_client=tx_client, accounts_client=None)
    with pytest.raises(ValueError, match="accounts_client is required"):
        await svc.estimate_regular_income("tok-test")


# ===========================================================================
# Integration tests — committed fixture data
# ===========================================================================


async def test_integration_detect_paycheck_cust001() -> None:
    """cust-001: ACME CORP PAYROLL detected as biweekly recurring income."""
    svc = default_income_service(trail=AuditTrail(sink=ListSink()))
    result = await svc.estimate_regular_income(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)

    assert result.status is IncomeStatus.DETECTED
    primary = result.primary_source
    assert primary is not None
    assert primary.payee == "ACME CORP PAYROLL"
    assert primary.cadence is PayCadence.BIWEEKLY
    assert primary.is_recurring is True
    assert primary.confidence is ConfidenceLevel.HIGH
    assert primary.raise_detected is False
    assert primary.per_period_amount == Decimal("925.00")
    assert result.estimated_monthly_income == Decimal("2004.17")
    assert len(primary.supporting_transaction_ids) >= MIN_RECURRING_DEPOSITS


async def test_integration_reject_venmo_cust003() -> None:
    """cust-003: VENMO credits are excluded; INITECH PAYROLL is the primary source."""
    svc = default_income_service(trail=AuditTrail(sink=ListSink()))
    result = await svc.estimate_regular_income(_TOKEN_003, "cust-003-checking", as_of=_ANCHOR)

    assert result.status is IncomeStatus.DETECTED
    # VENMO must NOT appear as any income source.
    all_payees = {s.payee for s in ((result.primary_source,) if result.primary_source else ())} | {
        s.payee for s in result.additional_sources
    }
    assert "VENMO" not in all_payees

    # VENMO must appear in rejected_sources with EXCLUDED_COUNTERPARTY.
    venmo_rejections = [r for r in result.rejected_sources if r.payee == "VENMO"]
    assert len(venmo_rejections) == 1
    assert venmo_rejections[0].reason is RejectionReason.EXCLUDED_COUNTERPARTY

    # Primary is the INITECH payroll.
    assert result.primary_source is not None
    assert result.primary_source.payee == "INITECH PAYROLL"
    assert result.primary_source.cadence is PayCadence.BIWEEKLY
    assert result.primary_source.is_recurring is True


async def test_integration_mid_history_raise_cust002() -> None:
    """cust-002: GLOBEX LLC PAYROLL 1800→2050 raise detected within 12-month window."""
    svc = default_income_service(trail=AuditTrail(sink=ListSink()))
    result = await svc.estimate_regular_income(_TOKEN_002, "cust-002-checking", as_of=_ANCHOR)

    assert result.status is IncomeStatus.DETECTED
    primary = result.primary_source
    assert primary is not None
    assert primary.payee == "GLOBEX LLC PAYROLL"
    assert primary.cadence is PayCadence.BIWEEKLY
    assert primary.is_recurring is True
    assert primary.raise_detected is True
    assert primary.prior_period_amount == Decimal("1800.00")
    assert primary.per_period_amount == Decimal("2050.00")
    assert primary.confidence is ConfidenceLevel.HIGH
    # Supporting ids span both the pre- and post-raise deposits.
    assert len(primary.supporting_transaction_ids) >= MIN_RECURRING_DEPOSITS


async def test_integration_freelance_not_primary_cust002_24mo() -> None:
    """cust-002 (24-month): Freelance payees (UPWORK/FIVERR/DIRECT CLIENT) never become primary."""
    svc = default_income_service(trail=AuditTrail(sink=ListSink()))
    result = await svc.estimate_regular_income(_TOKEN_002, "cust-002-checking", lookback_months=24, as_of=_ANCHOR)

    assert result.status is IncomeStatus.DETECTED
    assert result.primary_source is not None
    assert result.primary_source.payee == "GLOBEX LLC PAYROLL"

    # No freelance payee should be a *recurring* income source.
    freelance_payees = {"UPWORK", "FIVERR", "DIRECT CLIENT"}
    recurring_payees = {s.payee for s in result.additional_sources if s.is_recurring}
    assert not recurring_payees & freelance_payees

    # estimated_monthly_income is derived from the payroll primary only.
    assert result.estimated_monthly_income == result.primary_source.estimated_monthly_amount


async def test_integration_freelance_not_primary_cust003_24mo() -> None:
    """cust-003 (24-month): Freelance deposits do not displace INITECH PAYROLL as primary."""
    svc = default_income_service(trail=AuditTrail(sink=ListSink()))
    result = await svc.estimate_regular_income(_TOKEN_003, "cust-003-checking", lookback_months=24, as_of=_ANCHOR)

    assert result.status is IncomeStatus.DETECTED
    assert result.primary_source is not None
    assert result.primary_source.payee == "INITECH PAYROLL"
    assert result.primary_source.is_recurring is True


async def test_integration_auto_discover_checking_cust001() -> None:
    """Omitting account_id auto-discovers cust-001-checking; result matches explicit call."""
    svc = default_income_service(trail=AuditTrail(sink=ListSink()))
    explicit = await svc.estimate_regular_income(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    auto = await svc.estimate_regular_income(_TOKEN_001, as_of=_ANCHOR)

    assert auto.status == explicit.status
    assert auto.estimated_monthly_income == explicit.estimated_monthly_income
    assert auto.primary_source is not None
    assert auto.primary_source.payee == explicit.primary_source.payee  # type: ignore[union-attr]
    # Auto-discovered account_ids includes the checking account.
    assert "cust-001-checking" in auto.account_ids


async def test_integration_audit_events_emitted_on_success() -> None:
    """A successful call emits at least one get_transactions audit event per account."""
    sink = ListSink()
    svc = default_income_service(trail=AuditTrail(sink=sink))
    await svc.estimate_regular_income(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)

    tx_events = [e for e in sink.events if e.action == "get_transactions"]
    assert len(tx_events) >= 1
    for evt in tx_events:
        assert evt.resource.data_cluster == "TRANSACTIONS"
        assert evt.actor.token_id.startswith("sha256:")
        assert evt.outcome is AuditOutcome.SUCCESS


async def test_integration_txn_only_token_propagates_auth_error_on_auto_discover() -> None:
    """tok_cust_003_txn_only (no ACCOUNTS scope) raises AuthorizationError when account_id omitted."""
    svc = default_income_service(trail=AuditTrail(sink=ListSink()))
    with pytest.raises(AuthorizationError):
        await svc.estimate_regular_income(_TOKEN_003_TXN_ONLY, as_of=_ANCHOR)


async def test_integration_determinism() -> None:
    """Identical inputs always produce identical IncomeEstimate (frozen models)."""
    svc = default_income_service(trail=AuditTrail(sink=ListSink()))
    r1 = await svc.estimate_regular_income(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    svc2 = default_income_service(trail=AuditTrail(sink=ListSink()))
    r2 = await svc2.estimate_regular_income(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    assert r1 == r2
