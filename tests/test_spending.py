"""Tests for the spending-analysis service and its pure helper functions.

Structure
---------
- Pure unit tests on ``_to_spend_event``, ``_is_transfer``, ``_classify_group_as_recurring``,
  and ``_detect_outliers`` — no I/O, run synchronously.
- Service unit tests using ``_FakeSpendSource`` — synthetic transactions, no filesystem.
- Integration tests against the committed fixture data via ``default_spending_service``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from banking_client.analytics.results import (
    NotableKind,
    PayCadence,
    SpendingStatus,
)
from banking_client.analytics.spending import (
    _REFUND_CATEGORY_ID,
    _TRANSFER_CATEGORY_ID,
    MIN_RECURRING_OCCURRENCES,
    _classify_group_as_recurring,
    _detect_outliers,
    _is_transfer,
    _SpendEvent,
    _to_spend_event,
    default_spending_service,
)
from banking_client.auth import Authorizer, DataCluster
from banking_client.auth.scope import ConsentScope
from banking_client.client.transactions import TransactionsClient
from banking_client.models.enums import DebitCreditMemo, TransactionStatus
from banking_client.models.money import Money
from banking_client.models.transaction import Transaction, TransactionCategory
from common.audit import AuditOutcome, AuditTrail, ListSink
from common.errors import AuthorizationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ANCHOR = datetime(2026, 6, 30, tzinfo=UTC)
_TOKEN_001 = "tok_cust_001"
_TOKEN_002 = "tok_cust_002"
_TOKEN_003 = "tok_cust_003"
_TOKEN_003_TXN_ONLY = "tok_cust_003_txn_only"

_CAT_RENT = TransactionCategory(id="CAT-RENT", name="Rent")
_CAT_SUBS = TransactionCategory(id="CAT-SUBSCRIPTION", name="Subscription")
_CAT_GROC = TransactionCategory(id="CAT-GROCERIES", name="Groceries")
_CAT_SHOP = TransactionCategory(id="CAT-SHOPPING", name="Shopping")
_CAT_REFUND = TransactionCategory(id=_REFUND_CATEGORY_ID, name="Refund")
_CAT_TRANSFER = TransactionCategory(id=_TRANSFER_CATEGORY_ID, name="Transfer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _txn(
    amount: str = "100.00",
    memo: DebitCreditMemo = DebitCreditMemo.DEBIT,
    payee: str | None = "LANDLORD",
    category: TransactionCategory | None = _CAT_RENT,
    posted: datetime | None = datetime(2026, 6, 1, tzinfo=UTC),
    status: TransactionStatus = TransactionStatus.POSTED,
    txn_id: str = "txn-001",
) -> Transaction:
    resolved = posted if status is TransactionStatus.POSTED else None
    return Transaction(
        id=txn_id,
        account_id="test-checking",
        amount=Money(value=Decimal(amount), currency="USD"),
        posted_timestamp=resolved,
        transaction_timestamp=posted or datetime(2025, 7, 1, tzinfo=UTC),
        description="TEST",
        debit_credit_memo=memo,
        category=category,
        status=status,
        payee=payee,
    )


def _spend_event(
    amount: str,
    posted: datetime,
    payee: str | None = "LANDLORD",
    category_id: str = "CAT-RENT",
    category_name: str = "Rent",
    is_credit: bool = False,
    txn_id: str = "txn-001",
) -> _SpendEvent:
    return _SpendEvent(
        txn_id=txn_id,
        amount=Decimal(amount),
        posted=posted,
        payee=payee,
        category_id=category_id,
        category_name=category_name,
        is_credit=is_credit,
    )


def _monthly_events(
    n: int,
    amount: str,
    start: datetime,
    payee: str = "LANDLORD",
    category_id: str = "CAT-RENT",
    category_name: str = "Rent",
) -> list[_SpendEvent]:
    """Build *n* _SpendEvent objects spaced exactly 30 days apart."""
    return [
        _SpendEvent(
            txn_id=f"txn-mo-{i:04d}",
            amount=Decimal(amount),
            posted=start + timedelta(days=30 * i),
            payee=payee,
            category_id=category_id,
            category_name=category_name,
            is_credit=False,
        )
        for i in range(n)
    ]


def _scope(
    *,
    customer_id: str = "cust-test",
    account_ids: list[str] | None = None,
    clusters: list[DataCluster] | None = None,
) -> ConsentScope:
    return ConsentScope(
        consent_id=f"consent-{customer_id}",
        customer_id=customer_id,
        account_ids=frozenset(account_ids or ["test-checking"]),
        data_clusters=frozenset(clusters or [DataCluster.TRANSACTIONS]),
        expires_at=None,
    )


class _FakeSpendSource:
    """In-memory TransactionDataSource backed by a static list."""

    def __init__(self, txns: list[Transaction]) -> None:
        self._txns = txns

    async def list_transactions(self, *, token: str, customer_id: str, account_id: str) -> list[Transaction]:
        return self._txns


def _fake_service(txns: list[Transaction], *, account_id: str = "test-checking") -> tuple[object, str]:
    """Return (SpendingService, token) wired to an in-memory fake source."""
    from banking_client.analytics.spending import SpendingService

    source = _FakeSpendSource(txns)
    trail = AuditTrail(sink=ListSink())
    resolver = _FakeResolver({"test-tok": _scope(account_ids=[account_id])})
    auth = Authorizer(resolver=resolver)  # type: ignore[arg-type]
    tx_client = TransactionsClient(
        data_source=source,  # type: ignore[arg-type]
        authorizer=auth,
        trail=trail,
    )
    svc = SpendingService(transactions_client=tx_client)
    return svc, "test-tok"


class _FakeResolver:
    def __init__(self, registry: dict[str, ConsentScope]) -> None:
        self._registry = registry

    def resolve(self, token: str) -> ConsentScope:
        from common.errors import AuthenticationError

        scope = self._registry.get(token)
        if scope is None:
            raise AuthenticationError(f"Unknown token: {token!r}")
        return scope


# ===========================================================================
# _to_spend_event — pure unit tests
# ===========================================================================


def test_to_spend_event_debit_returns_event() -> None:
    """A POSTED DEBIT produces a _SpendEvent with is_credit=False."""
    ev = _to_spend_event(_txn(memo=DebitCreditMemo.DEBIT))
    assert ev is not None
    assert ev.is_credit is False
    assert ev.amount == Decimal("100.00")
    assert ev.category_id == "CAT-RENT"


def test_to_spend_event_credit_non_refund_returns_none() -> None:
    """A non-refund CREDIT (e.g. payroll) is discarded — not spend."""
    payroll_cat = TransactionCategory(id="CAT-PAYROLL", name="Payroll")
    ev = _to_spend_event(_txn(memo=DebitCreditMemo.CREDIT, category=payroll_cat))
    assert ev is None


def test_to_spend_event_refund_credit_is_kept() -> None:
    """A CREDIT with category CAT-REFUND is kept and marked is_credit=True."""
    ev = _to_spend_event(_txn(memo=DebitCreditMemo.CREDIT, category=_CAT_REFUND, payee="Amazon"))
    assert ev is not None
    assert ev.is_credit is True
    assert ev.payee == "Amazon"
    assert ev.category_id == _REFUND_CATEGORY_ID


def test_to_spend_event_pending_debit_returns_none() -> None:
    """A PENDING DEBIT (no posted_timestamp) is discarded."""
    tx = _txn(status=TransactionStatus.PENDING, posted=None)
    ev = _to_spend_event(tx)
    assert ev is None


def test_to_spend_event_no_category_is_allowed() -> None:
    """A DEBIT without a category produces a _SpendEvent with category_id=None."""
    ev = _to_spend_event(_txn(category=None))
    assert ev is not None
    assert ev.category_id is None
    assert ev.category_name is None


def test_to_spend_event_does_not_read_description() -> None:
    """The _SpendEvent carries no description — 1033 minimization."""
    ev = _to_spend_event(_txn())
    assert ev is not None
    assert not hasattr(ev, "description")


# ===========================================================================
# _is_transfer — pure unit tests
# ===========================================================================


def test_is_transfer_by_category() -> None:
    """Category CAT-TRANSFER routes the event to the transfers bucket."""
    ev = _spend_event(
        "400.00",
        datetime(2025, 7, 3, tzinfo=UTC),
        payee="INTERNAL TRANSFER",
        category_id=_TRANSFER_CATEGORY_ID,
        category_name="Transfer",
    )
    assert _is_transfer(ev) is True


def test_is_transfer_by_payee_only() -> None:
    """Payee 'INTERNAL TRANSFER' is enough to route to transfers, even with no category."""
    ev = _spend_event(
        "400.00",
        datetime(2025, 7, 3, tzinfo=UTC),
        payee="Internal Transfer",
        category_id="CAT-OTHER",
        category_name="Other",
    )
    assert _is_transfer(ev) is True


def test_is_transfer_false_for_rent() -> None:
    """Rent is not a transfer."""
    ev = _spend_event("2100.00", datetime(2025, 7, 1, tzinfo=UTC))
    assert _is_transfer(ev) is False


# ===========================================================================
# _classify_group_as_recurring — pure unit tests
# ===========================================================================


def test_classify_monthly_single_payee_is_fixed() -> None:
    """12 monthly occurrences from a single payee → RecurringCost MONTHLY."""
    events = _monthly_events(12, "2100.00", datetime(2025, 7, 1, tzinfo=UTC))
    rc = _classify_group_as_recurring("CAT-RENT", "Rent", "LANDLORD", events)
    assert rc is not None
    assert rc.cadence is PayCadence.MONTHLY
    assert rc.average_amount == Decimal("2100.00")
    assert rc.occurrence_count == 12
    assert len(rc.supporting_transaction_ids) == 12


def test_classify_too_few_occurrences_returns_none() -> None:
    """Fewer than MIN_RECURRING_OCCURRENCES → variable (None)."""
    events = _monthly_events(MIN_RECURRING_OCCURRENCES - 1, "11.99", datetime(2025, 7, 15, tzinfo=UTC), payee="NETFLIX")
    rc = _classify_group_as_recurring("CAT-SUBSCRIPTION", "Subscription", "NETFLIX", events)
    assert rc is None


def test_classify_irregular_cadence_returns_none() -> None:
    """Events with 2-day gaps (median=2, below all cadence buckets) → variable (None)."""
    base = datetime(2025, 7, 1, tzinfo=UTC)
    events = [
        _SpendEvent(
            txn_id=f"txn-{i}",
            amount=Decimal("50"),
            posted=base + timedelta(days=2 * i),
            payee="GROCERY",
            category_id="CAT-GROCERIES",
            category_name="Groceries",
            is_credit=False,
        )
        for i in range(6)
    ]
    rc = _classify_group_as_recurring("CAT-GROCERIES", "Groceries", "GROCERY", events)
    assert rc is None


def test_classify_jittered_monthly_still_fixed() -> None:
    """Monthly events with ±4 day jitter (utilities) → MONTHLY recurring."""
    base = datetime(2025, 7, 10, tzinfo=UTC)
    jitter = [0, 2, -3, 1, -1, 3, -2, 0, 2, -3, 1, 0]
    events = [
        _SpendEvent(
            txn_id=f"txn-util-{i}",
            amount=Decimal("180.00") + Decimal(str(j * 5)),
            posted=base + timedelta(days=30 * i + j),
            payee="METRO ENERGY",
            category_id="CAT-UTILITIES",
            category_name="Utilities",
            is_credit=False,
        )
        for i, j in enumerate(jitter)
    ]
    rc = _classify_group_as_recurring("CAT-UTILITIES", "Utilities", "METRO ENERGY", events)
    assert rc is not None
    assert rc.cadence is PayCadence.MONTHLY


def test_classify_estimated_monthly_amount_correct() -> None:
    """estimated_monthly_amount for MONTHLY cadence equals average_amount × 1."""
    events = _monthly_events(12, "24.99", datetime(2025, 7, 15, tzinfo=UTC), payee="SPOTIFY")
    rc = _classify_group_as_recurring("CAT-SUBSCRIPTION", "Subscription", "SPOTIFY", events)
    assert rc is not None
    assert rc.estimated_monthly_amount == rc.average_amount


# ===========================================================================
# _detect_outliers — pure unit tests
# ===========================================================================


def test_detect_outliers_flags_large_one_off() -> None:
    """An amount > OUTLIER_MULTIPLE × median is flagged."""
    base = datetime(2025, 7, 1, tzinfo=UTC)
    normal = [
        _SpendEvent(
            txn_id=f"txn-n{i}",
            amount=Decimal("95"),
            posted=base + timedelta(days=i),
            payee="Amazon",
            category_id="CAT-SHOPPING",
            category_name="Shopping",
            is_credit=False,
        )
        for i in range(10)
    ]
    outlier = _SpendEvent(
        txn_id="txn-big",
        amount=Decimal("2500.00"),
        posted=base + timedelta(days=30),
        payee="Best Buy",
        category_id="CAT-SHOPPING",
        category_name="Shopping",
        is_credit=False,
    )
    result = _detect_outliers(normal + [outlier])
    assert "txn-big" in result
    assert all(f"txn-n{i}" not in result for i in range(10))


def test_detect_outliers_returns_empty_when_too_few_samples() -> None:
    """Fewer than MIN_SAMPLES_FOR_OUTLIER events → no outlier detection attempted."""
    events = [
        _SpendEvent(
            txn_id=f"txn-{i}",
            amount=Decimal("1000"),
            posted=datetime(2025, 7, 1, tzinfo=UTC),
            payee="X",
            category_id="CAT-SHOPPING",
            category_name="Shopping",
            is_credit=False,
        )
        for i in range(3)
    ]
    assert _detect_outliers(events) == frozenset()


def test_detect_outliers_normal_variance_not_flagged() -> None:
    """Normal spending variance (±50 %) is not flagged as a one-off."""
    base = datetime(2025, 7, 1, tzinfo=UTC)
    events = [
        _SpendEvent(
            txn_id=f"txn-{i}",
            amount=Decimal(str(50 + i * 10)),
            posted=base + timedelta(days=i),
            payee="Store",
            category_id="CAT-GROCERIES",
            category_name="Groceries",
            is_credit=False,
        )
        for i in range(8)
    ]
    assert _detect_outliers(events) == frozenset()


def test_detect_outliers_zero_median_returns_empty() -> None:
    """If all amounts are zero the function returns empty (degenerate guard)."""
    events = [
        _SpendEvent(
            txn_id=f"txn-{i}",
            amount=Decimal("0"),
            posted=datetime(2025, 7, 1, tzinfo=UTC),
            payee="X",
            category_id="CAT-X",
            category_name="X",
            is_credit=False,
        )
        for i in range(5)
    ]
    assert _detect_outliers(events) == frozenset()


# ===========================================================================
# Service unit tests — synthetic in-memory data
# ===========================================================================


async def test_service_insufficient_history_when_no_debits() -> None:
    """No DEBIT transactions → INSUFFICIENT_HISTORY."""
    credit_only = [
        _txn(
            memo=DebitCreditMemo.CREDIT,
            category=TransactionCategory(id="CAT-PAYROLL", name="Payroll"),
            txn_id="txn-pay",
        ),
    ]
    svc, tok = _fake_service(credit_only)
    result = await svc.analyze_spending(tok, "test-checking", as_of=_ANCHOR)  # type: ignore[union-attr]
    assert result.status is SpendingStatus.INSUFFICIENT_HISTORY


async def test_service_transfer_excluded_from_spend_totals() -> None:
    """Self-transfer DEBIT is in transfers_monthly_total, not total_gross_spend."""
    transfer_tx = _txn(amount="400.00", category=_CAT_TRANSFER, payee="INTERNAL TRANSFER", txn_id="txn-xfer")
    spend_tx = _txn(amount="50.00", category=_CAT_GROC, payee="Trader Joe's", txn_id="txn-groc")
    svc, tok = _fake_service([transfer_tx, spend_tx])
    result = await svc.analyze_spending(tok, "test-checking", lookback_months=1, as_of=_ANCHOR)  # type: ignore[union-attr]
    assert result.total_gross_spend == Decimal("50.00")
    assert result.transfers_monthly_total == Decimal("400.00")


async def test_service_refund_nets_against_gross_spend() -> None:
    """total_net_spend == total_gross_spend - total_refunds (exact)."""
    spend_tx = _txn(amount="200.00", category=_CAT_SHOP, payee="Amazon", txn_id="txn-buy")
    refund_tx = _txn(
        amount="75.00", memo=DebitCreditMemo.CREDIT, category=_CAT_REFUND, payee="Amazon", txn_id="txn-ref"
    )
    svc, tok = _fake_service([spend_tx, refund_tx])
    result = await svc.analyze_spending(tok, "test-checking", lookback_months=1, as_of=_ANCHOR)  # type: ignore[union-attr]
    assert result.total_refunds == Decimal("75.00")
    assert result.total_gross_spend == Decimal("200.00")
    assert result.total_net_spend == Decimal("125.00")


async def test_service_monthly_avg_divides_by_lookback_months_not_active_months() -> None:
    """A single month of spend over a 12-month window lowers the monthly average."""
    spend_tx = _txn(
        amount="120.00", category=_CAT_GROC, payee="Store", txn_id="txn-once", posted=datetime(2026, 6, 1, tzinfo=UTC)
    )
    svc, tok = _fake_service([spend_tx])
    result = await svc.analyze_spending(tok, "test-checking", lookback_months=12, as_of=_ANCHOR)  # type: ignore[union-attr]
    # $120 over 12 months → $10/mo, not $120/mo (1 active month)
    cat = next(c for c in result.category_breakdown if c.category_id == "CAT-GROCERIES")
    assert cat.recurring_monthly_average == Decimal("10.00")


async def test_service_outlier_excluded_from_variable_monthly_total() -> None:
    """variable_monthly_total is computed without the large one-off amount."""
    base = datetime(2025, 7, 1, tzinfo=UTC)
    normal_txns = [
        _txn(
            amount="50.00",
            category=_CAT_SHOP,
            payee=f"Store{i}",
            txn_id=f"txn-sm{i}",
            posted=base + timedelta(days=10 * i),
        )
        for i in range(10)
    ]
    outlier_txn = _txn(
        amount="2500.00", category=_CAT_SHOP, payee="Best Buy", txn_id="txn-big", posted=base + timedelta(days=5)
    )
    svc, tok = _fake_service(normal_txns + [outlier_txn])
    result = await svc.analyze_spending(tok, "test-checking", lookback_months=12, as_of=_ANCHOR)  # type: ignore[union-attr]
    # variable_monthly_total should NOT include the $2500 outlier
    assert result.variable_monthly_total < Decimal("300.00")
    outlier_kinds = [n.kind for n in result.notable_items]
    assert NotableKind.LARGE_ONE_OFF in outlier_kinds


async def test_service_recurring_cost_in_category_breakdown_is_fixed() -> None:
    """A single-payee monthly group makes its category is_fixed=True in the breakdown."""
    events = [
        _txn(
            amount="2100.00",
            category=_CAT_RENT,
            payee="LANDLORD",
            txn_id=f"txn-rent{i}",
            posted=datetime(2025, 7, 1, tzinfo=UTC) + timedelta(days=30 * i),
        )
        for i in range(12)
    ]
    svc, tok = _fake_service(events)
    result = await svc.analyze_spending(tok, "test-checking", lookback_months=12, as_of=_ANCHOR)  # type: ignore[union-attr]
    rent_cat = next((c for c in result.category_breakdown if c.category_id == "CAT-RENT"), None)
    assert rent_cat is not None
    assert rent_cat.is_fixed is True


async def test_service_rotating_merchants_are_variable() -> None:
    """Rotating merchants with irregular per-payee cadence → is_fixed=False."""
    base = datetime(2025, 7, 1, tzinfo=UTC)
    groceries = [
        _txn(amount="55.00", category=_CAT_GROC, payee=p, txn_id=f"txn-gr{i}", posted=base + timedelta(days=4 * i))
        for i, p in enumerate(["Trader Joe's", "Safeway", "Whole Foods", "Kroger", "Costco", "Trader Joe's", "Safeway"])
    ]
    svc, tok = _fake_service(groceries)
    result = await svc.analyze_spending(tok, "test-checking", lookback_months=12, as_of=_ANCHOR)  # type: ignore[union-attr]
    groc_cat = next((c for c in result.category_breakdown if c.category_id == "CAT-GROCERIES"), None)
    assert groc_cat is not None
    assert groc_cat.is_fixed is False


async def test_service_determinism_identical_inputs_produce_identical_result() -> None:
    """Two calls with the same inputs produce byte-for-byte identical SpendingAnalysis."""
    trail = AuditTrail(sink=ListSink())
    svc = default_spending_service(trail=trail)
    r1 = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    r2 = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    assert r1 == r2


# ===========================================================================
# Integration tests — committed fixture data
# ===========================================================================


async def test_integration_cust001_recurring_costs_detected() -> None:
    """cust-001: rent, utilities, and subscription classified as recurring fixed costs."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", lookback_months=24, as_of=_ANCHOR)
    assert result.status is SpendingStatus.ANALYZED
    payees = {rc.payee for rc in result.recurring_costs}
    assert "SUNSET APARTMENTS" in payees
    assert "CITY POWER & WATER" in payees
    assert "NETFLIX" in payees


async def test_integration_cust001_no_savings_transfer() -> None:
    """cust-001 has no savings account, so transfers_monthly_total is zero."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", lookback_months=24, as_of=_ANCHOR)
    assert result.transfers_monthly_total == Decimal("0.00")


async def test_integration_cust001_refund_in_notable_items() -> None:
    """cust-001 has a refund CREDIT; it appears in notable_items as REFUND (24-month window)."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", lookback_months=24, as_of=_ANCHOR)
    refund_items = [n for n in result.notable_items if n.kind is NotableKind.REFUND]
    assert len(refund_items) == 1
    assert refund_items[0].payee == "AMAZON"


async def test_integration_cust001_net_spend_correct() -> None:
    """total_net_spend == total_gross_spend - total_refunds (24-month window)."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", lookback_months=24, as_of=_ANCHOR)
    assert result.total_net_spend == result.total_gross_spend - result.total_refunds


async def test_integration_cust001_fixed_categories_marked() -> None:
    """RENT, UTILITIES, SUBSCRIPTION categories are marked is_fixed=True."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", lookback_months=24, as_of=_ANCHOR)
    fixed_ids = {c.category_id for c in result.category_breakdown if c.is_fixed}
    assert "CAT-RENT" in fixed_ids
    assert "CAT-UTILITIES" in fixed_ids
    assert "CAT-SUBSCRIPTION" in fixed_ids


async def test_integration_cust001_variable_categories_not_fixed() -> None:
    """GROCERIES and DINING categories are marked is_fixed=False."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", lookback_months=24, as_of=_ANCHOR)
    for cat in result.category_breakdown:
        if cat.category_id in ("CAT-GROCERIES", "CAT-DINING"):
            assert cat.is_fixed is False, f"{cat.category_id} should not be fixed"


async def test_integration_cust002_large_purchase_flagged() -> None:
    """cust-002: large one-off purchase is in notable_items as LARGE_ONE_OFF."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_002, "cust-002-checking", as_of=_ANCHOR)
    one_offs = [n for n in result.notable_items if n.kind is NotableKind.LARGE_ONE_OFF]
    assert len(one_offs) == 1
    assert one_offs[0].payee == "BEST BUY"
    assert one_offs[0].amount >= Decimal("1600.00")


async def test_integration_cust002_large_purchase_excluded_from_variable_avg() -> None:
    """variable_monthly_total is materially lower than (gross − fixed) / months."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_002, "cust-002-checking", as_of=_ANCHOR)
    one_off_amount = sum(n.amount for n in result.notable_items if n.kind is NotableKind.LARGE_ONE_OFF)
    raw_variable = result.total_gross_spend - sum(
        rc.average_amount * rc.occurrence_count for rc in result.recurring_costs
    )
    # variable_monthly_total should be less than (raw_variable / 12) because the one-off is excluded
    assert result.variable_monthly_total < raw_variable / Decimal("12")
    # And the one-off itself is > 0
    assert one_off_amount > Decimal("0")


async def test_integration_cust002_refund_notable_and_netted() -> None:
    """cust-002 (24-month): refund appears in notable_items and net < gross."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_002, "cust-002-checking", lookback_months=24, as_of=_ANCHOR)
    refunds = [n for n in result.notable_items if n.kind is NotableKind.REFUND]
    assert len(refunds) == 1
    assert result.total_net_spend == result.total_gross_spend - result.total_refunds
    assert result.total_net_spend < result.total_gross_spend


async def test_integration_cust002_savings_transfer_excluded_from_spend() -> None:
    """$400/mo savings transfer is in transfers bucket, not in gross spend or category breakdown."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_002, "cust-002-checking", as_of=_ANCHOR)
    assert result.transfers_monthly_total == Decimal("400.00")
    transfer_in_cats = any(c.category_id == _TRANSFER_CATEGORY_ID for c in result.category_breakdown)
    assert not transfer_in_cats, "CAT-TRANSFER should not appear in category_breakdown"


async def test_integration_cust002_typical_monthly_excludes_oneoff_and_transfer() -> None:
    """typical_monthly_spend == fixed_monthly_total + variable_monthly_total (not one-off/transfer)."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_002, "cust-002-checking", as_of=_ANCHOR)
    expected = (result.fixed_monthly_total + result.variable_monthly_total).quantize(Decimal("0.01"))
    assert result.typical_monthly_spend == expected


async def test_integration_cust003_both_large_purchase_and_refund() -> None:
    """cust-003 (12-month): both LARGE_ONE_OFF and REFUND appear in notable_items."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_003, "cust-003-checking", as_of=_ANCHOR)
    kinds = {n.kind for n in result.notable_items}
    assert NotableKind.LARGE_ONE_OFF in kinds
    assert NotableKind.REFUND in kinds


async def test_integration_cust003_recurring_costs_correct() -> None:
    """cust-003: rent, utilities, Adobe CC, and NYT are recurring fixed costs."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_003, "cust-003-checking", as_of=_ANCHOR)
    payees = {rc.payee for rc in result.recurring_costs}
    assert "HARBORVIEW TOWERS" in payees
    assert "PACIFIC UTILITIES" in payees
    assert "ADOBE CC" in payees
    assert "NYT" in payees


async def test_integration_auto_discover_checking_matches_explicit_account() -> None:
    """Omitting account_id auto-discovers the checking account; result matches explicit call."""
    trail = AuditTrail(sink=ListSink())
    svc = default_spending_service(trail=trail)
    explicit = await svc.analyze_spending(_TOKEN_001, "cust-001-checking", lookback_months=24, as_of=_ANCHOR)
    auto = await svc.analyze_spending(_TOKEN_001, as_of=_ANCHOR, lookback_months=24)
    assert auto.total_gross_spend == explicit.total_gross_spend
    assert set(auto.account_ids) == set(explicit.account_ids)


async def test_integration_audit_events_emitted_for_get_transactions() -> None:
    """Each underlying get_transactions call emits an audit event with TRANSACTIONS cluster."""
    sink = ListSink()
    svc = default_spending_service(trail=AuditTrail(sink=sink))
    await svc.analyze_spending(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    tx_events = [e for e in sink.events if e.resource.data_cluster == "TRANSACTIONS"]
    assert len(tx_events) >= 1
    assert all(e.outcome is AuditOutcome.SUCCESS for e in tx_events)


async def test_integration_txn_only_token_propagates_auth_error_on_auto_discover() -> None:
    """tok_cust_003_txn_only (no ACCOUNTS scope) raises AuthorizationError when account_id omitted."""
    svc = default_spending_service()
    with pytest.raises(AuthorizationError):
        await svc.analyze_spending(_TOKEN_003_TXN_ONLY)


async def test_integration_supporting_txn_ids_nonempty() -> None:
    """Every recurring cost and category summary has non-empty supporting_transaction_ids."""
    svc = default_spending_service()
    result = await svc.analyze_spending(_TOKEN_002, "cust-002-checking", as_of=_ANCHOR)
    for rc in result.recurring_costs:
        assert len(rc.supporting_transaction_ids) >= MIN_RECURRING_OCCURRENCES
    for cat in result.category_breakdown:
        assert len(cat.supporting_transaction_ids) >= 1


async def test_integration_regression_income_tests_unaffected() -> None:
    """The income service still works correctly after the _recurrence extraction (regression guard)."""
    from banking_client.analytics.income import default_income_service

    svc = default_income_service()
    result = await svc.estimate_regular_income(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    from banking_client.analytics.results import IncomeStatus

    assert result.status is IncomeStatus.DETECTED
    assert result.primary_source is not None
    assert result.primary_source.payee == "ACME CORP PAYROLL"
