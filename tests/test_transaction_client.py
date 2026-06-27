"""Tests for the async FDX transaction client.

Covers TransactionsClient (get_transactions), FixtureTransactionDataSource, date-range
filtering, pending/posted status filtering, pagination across the full 24-month window,
typed errors, audit one-event-per-call guarantee, and a real-wiring integration smoke test
against the committed fixtures + consents.json.

Test structure
--------------
- Hermetic unit tests use _FakeTxnSource (in-memory, Protocol-compatible) + a real Authorizer
  over a _FakeResolver so the actual guard logic runs under controlled scopes.
- Audit assertions inject AuditTrail(sink=ListSink()) via TransactionsClient(trail=...).
- The integration test at the bottom uses default_transactions_client() to exercise the full
  stack against the committed 24-month fixture files.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from banking_client.auth import Authorizer, DataCluster
from banking_client.auth.resolver import ConsentResolver
from banking_client.auth.scope import ConsentScope
from banking_client.client import (
    FixtureTransactionDataSource,
    InvalidDateRangeError,
    InvalidPageCursorError,
    TransactionDataSource,
    TransactionsClient,
    default_fixture_data_dir,
    default_transactions_client,
)
from banking_client.client.pagination import _encode_cursor
from banking_client.client.transactions import _in_date_window
from banking_client.models.enums import DebitCreditMemo, TransactionStatus
from banking_client.models.money import Money
from banking_client.models.transaction import Transaction, TransactionCategory
from common.audit import AuditOutcome, AuditTrail, ListSink
from common.errors import AuthenticationError, AuthorizationError

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_TOKEN_003 = "tok_cust_003"  # ACCOUNTS + TRANSACTIONS, cust-003-checking + cust-003-savings
_TOKEN_001 = "tok_cust_001"  # ACCOUNTS + TRANSACTIONS, cust-001-checking
_TOKEN_003_TXN_ONLY = "tok_cust_003_txn_only"  # TRANSACTIONS only, cust-003-checking
_TOKEN_EXPIRED = "tok_expired"
_TOKEN_UNKNOWN = "tok_unknown"
_TOKEN_ACCOUNTS_ONLY = "tok_cust_001_accounts_only"  # ACCOUNTS only — no TRANSACTIONS

_NOW_FIXED = datetime(2026, 1, 1, tzinfo=UTC)
_PAST = _NOW_FIXED - timedelta(days=1)

# Representative dates within the 24-month window (2024-06-30 → 2026-06-30).
_JAN_2025 = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
_JUN_2025 = datetime(2025, 6, 15, 12, 0, tzinfo=UTC)
_DEC_2025 = datetime(2025, 12, 15, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# In-memory consent resolver
# ---------------------------------------------------------------------------


class _FakeResolver:
    """Minimal ConsentResolver satisfied by a static dict (no filesystem)."""

    def __init__(self, registry: dict[str, ConsentScope]) -> None:
        """Bind the registry dict."""
        self._registry = registry

    def resolve(self, token: str) -> ConsentScope:
        """Return the scope for *token*, raising AuthenticationError if absent or expired."""
        scope = self._registry.get(token)
        if scope is None:
            raise AuthenticationError(f"Unknown bearer token: {token!r}")
        if scope.expires_at is not None and scope.expires_at <= _NOW_FIXED:
            raise AuthenticationError(f"Bearer token {token!r} has expired")
        return scope


def _scope(
    *,
    customer_id: str,
    account_ids: list[str],
    clusters: list[DataCluster] | None = None,
    expires_at: datetime | None = None,
) -> ConsentScope:
    """Build a ConsentScope; defaults to ACCOUNTS + TRANSACTIONS."""
    return ConsentScope(
        consent_id=f"consent-{customer_id}",
        customer_id=customer_id,
        account_ids=frozenset(account_ids),
        data_clusters=frozenset(
            clusters if clusters is not None else [DataCluster.ACCOUNTS, DataCluster.TRANSACTIONS]
        ),
        expires_at=expires_at,
    )


_REGISTRY: dict[str, ConsentScope] = {
    _TOKEN_001: _scope(customer_id="cust-001", account_ids=["cust-001-checking"]),
    _TOKEN_003: _scope(customer_id="cust-003", account_ids=["cust-003-checking", "cust-003-savings"]),
    _TOKEN_003_TXN_ONLY: _scope(
        customer_id="cust-003",
        account_ids=["cust-003-checking"],
        clusters=[DataCluster.TRANSACTIONS],
    ),
    _TOKEN_ACCOUNTS_ONLY: _scope(
        customer_id="cust-001",
        account_ids=["cust-001-checking"],
        clusters=[DataCluster.ACCOUNTS],
    ),
    _TOKEN_EXPIRED: _scope(
        customer_id="cust-001",
        account_ids=["cust-001-checking"],
        expires_at=_PAST,
    ),
}


# ---------------------------------------------------------------------------
# In-memory transaction data source (Protocol-compatible; no filesystem)
# ---------------------------------------------------------------------------


def _money(value: str, currency: str = "USD") -> Money:
    """Build a Money instance."""
    return Money(value=Decimal(value), currency=currency)


def _txn(
    txn_id: str,
    account_id: str,
    *,
    when: datetime,
    posted: datetime | None = None,
    status: TransactionStatus = TransactionStatus.POSTED,
    amount: str = "10.00",
    memo: DebitCreditMemo = DebitCreditMemo.DEBIT,
    description: str = "TEST TXN",
    category: TransactionCategory | None = None,
    payee: str | None = None,
) -> Transaction:
    """Build a Transaction with sensible defaults.

    If *status* is POSTED and *posted* is not given, defaults *posted* to *when*
    (same-day settle), matching the synthetic data generator's behavior.
    """
    resolved_posted: datetime | None = posted
    if status is TransactionStatus.POSTED and resolved_posted is None:
        resolved_posted = when
    return Transaction(
        id=txn_id,
        account_id=account_id,
        amount=_money(amount),
        transaction_timestamp=when,
        posted_timestamp=resolved_posted,
        description=description,
        debit_credit_memo=memo,
        category=category,
        status=status,
        payee=payee,
    )


# 6 transactions across a ~1-year span on cust-001-checking.
_T_JAN = _txn("t-001", "cust-001-checking", when=_JAN_2025, amount="100.00")
_T_JUN = _txn("t-002", "cust-001-checking", when=_JUN_2025, amount="200.00")
_T_DEC = _txn("t-003", "cust-001-checking", when=_DEC_2025, amount="300.00")
_T_PENDING_1 = _txn(
    "t-004",
    "cust-001-checking",
    when=_DEC_2025 + timedelta(days=5),
    status=TransactionStatus.PENDING,
)
_T_PENDING_2 = _txn(
    "t-005",
    "cust-001-checking",
    when=_DEC_2025 + timedelta(days=6),
    status=TransactionStatus.PENDING,
)
_T_CREDIT = _txn(
    "t-006",
    "cust-001-checking",
    when=_JUN_2025 + timedelta(days=1),
    memo=DebitCreditMemo.CREDIT,
    amount="500.00",
)

_ALL_TXNS = [_T_JAN, _T_JUN, _T_DEC, _T_PENDING_1, _T_PENDING_2, _T_CREDIT]


class _FakeTxnSource:
    """In-memory TransactionDataSource for unit tests (Protocol-compatible)."""

    def __init__(self, transactions: dict[str, list[Transaction]]) -> None:
        """Bind account_id → transaction list."""
        self._transactions = transactions

    async def list_transactions(
        self,
        *,
        token: str,
        customer_id: str,
        account_id: str,
    ) -> list[Transaction]:
        """Return transactions for *account_id*, or empty list."""
        return self._transactions.get(account_id, [])


_DEFAULT_SOURCE = _FakeTxnSource({"cust-001-checking": _ALL_TXNS})


# ---------------------------------------------------------------------------
# Client and trail builder helpers
# ---------------------------------------------------------------------------


def _trail_and_sink() -> tuple[AuditTrail, ListSink]:
    """Return a fresh (AuditTrail, ListSink) pair for audit assertions."""
    sink = ListSink()
    return AuditTrail(sink=sink), sink


def _client(
    source: TransactionDataSource | None = None,
    *,
    trail: AuditTrail | None = None,
    page_size: int = 25,
    registry: dict[str, ConsentScope] | None = None,
) -> TransactionsClient:
    """Build a TransactionsClient over the fake resolver + supplied source.

    Always injects an AuditTrail(sink=ListSink()) when no trail is supplied so that
    tests never create a process-global StdoutJSONSink.
    """
    resolver: ConsentResolver = _FakeResolver(registry if registry is not None else _REGISTRY)
    authorizer = Authorizer(resolver)
    if trail is None:
        trail = AuditTrail(sink=ListSink())
    return TransactionsClient(
        data_source=source if source is not None else _DEFAULT_SOURCE,
        authorizer=authorizer,
        trail=trail,
        page_size=page_size,
    )


# ===========================================================================
# _in_date_window — unit tests for the module-level filter helper
# ===========================================================================


def test_in_date_window_no_bounds_posted_passes() -> None:
    """A POSTED transaction passes when neither bound is set."""
    tx = _txn("x", "a", when=_JAN_2025)
    assert _in_date_window(tx, None, None) is True


def test_in_date_window_no_bounds_pending_passes() -> None:
    """A PENDING transaction passes when neither bound is set."""
    tx = _txn("x", "a", when=_JAN_2025, status=TransactionStatus.PENDING)
    assert _in_date_window(tx, None, None) is True


def test_in_date_window_pending_excluded_when_start_set() -> None:
    """A PENDING transaction is excluded whenever start_time is set."""
    tx = _txn("x", "a", when=_JAN_2025, status=TransactionStatus.PENDING)
    assert _in_date_window(tx, _JAN_2025, None) is False


def test_in_date_window_pending_excluded_when_end_set() -> None:
    """A PENDING transaction is excluded whenever end_time is set."""
    tx = _txn("x", "a", when=_JAN_2025, status=TransactionStatus.PENDING)
    assert _in_date_window(tx, None, _DEC_2025) is False


def test_in_date_window_posted_before_start_excluded() -> None:
    """A POSTED transaction before start_time is excluded."""
    tx = _txn("x", "a", when=_JAN_2025)
    assert _in_date_window(tx, _JUN_2025, None) is False


def test_in_date_window_posted_after_end_excluded() -> None:
    """A POSTED transaction after end_time is excluded."""
    tx = _txn("x", "a", when=_DEC_2025)
    assert _in_date_window(tx, None, _JUN_2025) is False


def test_in_date_window_posted_on_start_boundary_included() -> None:
    """A POSTED transaction exactly on start_time is included (inclusive)."""
    tx = _txn("x", "a", when=_JAN_2025)
    assert _in_date_window(tx, _JAN_2025, None) is True


def test_in_date_window_posted_on_end_boundary_included() -> None:
    """A POSTED transaction exactly on end_time is included (inclusive)."""
    tx = _txn("x", "a", when=_JAN_2025)
    assert _in_date_window(tx, None, _JAN_2025) is True


def test_in_date_window_posted_within_both_bounds_included() -> None:
    """A POSTED transaction inside [start, end] is included."""
    tx = _txn("x", "a", when=_JUN_2025)
    assert _in_date_window(tx, _JAN_2025, _DEC_2025) is True


def test_in_date_window_posted_outside_closed_range_excluded() -> None:
    """A POSTED transaction outside a closed [start, end] range is excluded."""
    tx = _txn("x", "a", when=_JAN_2025 - timedelta(days=1))
    assert _in_date_window(tx, _JAN_2025, _DEC_2025) is False


# ===========================================================================
# get_transactions — happy path
# ===========================================================================


async def test_get_transactions_returns_paginated_response() -> None:
    """get_transactions returns a PaginatedResponse[Transaction] of typed models."""
    client = _client()
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert result.page.total == len(_ALL_TXNS)
    assert all(isinstance(tx, Transaction) for tx in result.items)


async def test_get_transactions_default_page_includes_all_when_below_page_size() -> None:
    """With 6 transactions and default page_size=25, all fit on one page."""
    client = _client()
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert len(result.items) == len(_ALL_TXNS)
    assert result.page.next_offset is None


async def test_get_transactions_results_sorted_by_timestamp_then_id() -> None:
    """Results are sorted by (transaction_timestamp, id) ascending."""
    client = _client()
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking")
    timestamps = [(tx.transaction_timestamp, tx.id) for tx in result.items]
    assert timestamps == sorted(timestamps)


async def test_get_transactions_empty_account_returns_empty_items() -> None:
    """An account with no transactions returns an empty items list with total=0."""
    source = _FakeTxnSource({"cust-001-checking": []})
    client = _client(source)
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert result.items == []
    assert result.page.total == 0
    assert result.page.next_offset is None


async def test_get_transactions_token_with_txn_only_scope_succeeds() -> None:
    """A token with TRANSACTIONS-only scope can call get_transactions."""
    source = _FakeTxnSource({"cust-003-checking": [_txn("x", "cust-003-checking", when=_JAN_2025)]})
    client = _client(source)
    result = await client.get_transactions(_TOKEN_003_TXN_ONLY, "cust-003-checking")
    assert result.page.total == 1


# ===========================================================================
# get_transactions — date filtering correctness
# ===========================================================================


async def test_get_transactions_start_time_filters_earlier_transactions() -> None:
    """Transactions before start_time are excluded."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", start_time=_JUN_2025
    )
    for tx in result.items:
        assert tx.posted_timestamp is not None
        assert tx.posted_timestamp >= _JUN_2025


async def test_get_transactions_end_time_filters_later_transactions() -> None:
    """Transactions after end_time are excluded."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", end_time=_JUN_2025
    )
    for tx in result.items:
        assert tx.posted_timestamp is not None
        assert tx.posted_timestamp <= _JUN_2025


async def test_get_transactions_closed_date_range_returns_matching_only() -> None:
    """A closed [start, end] window returns only transactions within it."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001,
        "cust-001-checking",
        start_time=_JAN_2025,
        end_time=_JUN_2025,
    )
    for tx in result.items:
        assert tx.posted_timestamp is not None
        assert _JAN_2025 <= tx.posted_timestamp <= _JUN_2025


async def test_get_transactions_date_range_boundary_inclusive_start() -> None:
    """A transaction exactly on start_time is included."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", start_time=_JAN_2025, end_time=_JAN_2025
    )
    assert any(tx.id == _T_JAN.id for tx in result.items)


async def test_get_transactions_date_range_boundary_inclusive_end() -> None:
    """A transaction exactly on end_time is included."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", start_time=_JAN_2025, end_time=_JAN_2025
    )
    assert any(tx.id == _T_JAN.id for tx in result.items)


async def test_get_transactions_date_range_excludes_pending() -> None:
    """PENDING transactions are excluded when any date bound is set."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001,
        "cust-001-checking",
        start_time=_JAN_2025,
        end_time=_DEC_2025 + timedelta(days=10),
    )
    for tx in result.items:
        assert tx.status == TransactionStatus.POSTED


async def test_get_transactions_no_bounds_includes_pending() -> None:
    """With no date bounds and no status filter, PENDING transactions are included."""
    client = _client()
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking")
    pending = [tx for tx in result.items if tx.status == TransactionStatus.PENDING]
    assert len(pending) == 2


async def test_get_transactions_date_range_total_reflects_filtered_count() -> None:
    """page.total is the post-filter count, not the raw transaction count."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001,
        "cust-001-checking",
        start_time=_JAN_2025,
        end_time=_JAN_2025,
    )
    assert result.page.total == len(result.items)


# ===========================================================================
# get_transactions — PENDING / POSTED status filtering
# ===========================================================================


async def test_get_transactions_status_posted_returns_posted_only() -> None:
    """status=POSTED filters out pending transactions."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", status=TransactionStatus.POSTED
    )
    assert result.items
    for tx in result.items:
        assert tx.status == TransactionStatus.POSTED


async def test_get_transactions_status_pending_returns_pending_only() -> None:
    """status=PENDING filters out posted transactions."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", status=TransactionStatus.PENDING
    )
    assert result.items
    for tx in result.items:
        assert tx.status == TransactionStatus.PENDING


async def test_get_transactions_status_none_returns_all() -> None:
    """status=None (default) returns both PENDING and POSTED."""
    client = _client()
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking", status=None)
    statuses = {tx.status for tx in result.items}
    assert TransactionStatus.POSTED in statuses
    assert TransactionStatus.PENDING in statuses


async def test_get_transactions_status_posted_count_matches_posted_in_source() -> None:
    """The count of status=POSTED results matches the posted transactions in the source."""
    client = _client()
    all_result = await client.get_transactions(_TOKEN_001, "cust-001-checking")
    posted_count = sum(1 for tx in all_result.items if tx.status == TransactionStatus.POSTED)

    posted_result = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", status=TransactionStatus.POSTED
    )
    assert posted_result.page.total == posted_count


async def test_get_transactions_posted_only_with_date_range_combines_both_filters() -> None:
    """status=POSTED combined with a date range applies both filters independently."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001,
        "cust-001-checking",
        start_time=_JAN_2025,
        end_time=_DEC_2025,
        status=TransactionStatus.POSTED,
    )
    for tx in result.items:
        assert tx.status == TransactionStatus.POSTED
        assert tx.posted_timestamp is not None
        assert _JAN_2025 <= tx.posted_timestamp <= _DEC_2025


# ===========================================================================
# get_transactions — pagination
# ===========================================================================


async def test_get_transactions_pagination_limit_slices_result() -> None:
    """limit=1 returns exactly 1 item."""
    client = _client()
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking", limit=1)
    assert len(result.items) == 1


async def test_get_transactions_pagination_next_offset_present_when_more_exist() -> None:
    """next_offset is set when there are more pages."""
    client = _client()
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking", limit=1)
    assert result.page.next_offset is not None


async def test_get_transactions_pagination_prev_offset_none_on_first_page() -> None:
    """prev_offset is None on the first page."""
    client = _client()
    result = await client.get_transactions(_TOKEN_001, "cust-001-checking", limit=2)
    assert result.page.prev_offset is None


async def test_get_transactions_pagination_second_page_returns_different_items() -> None:
    """Following next_offset delivers the next slice with different items."""
    client = _client()
    page1 = await client.get_transactions(_TOKEN_001, "cust-001-checking", limit=2)
    assert page1.page.next_offset is not None
    page2 = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", limit=2, page_key=page1.page.next_offset
    )
    ids1 = {tx.id for tx in page1.items}
    ids2 = {tx.id for tx in page2.items}
    assert ids1.isdisjoint(ids2)


async def test_get_transactions_pagination_middle_page_has_both_offsets() -> None:
    """A page that is neither first nor last has both next_offset and prev_offset."""
    client = _client()
    page1 = await client.get_transactions(_TOKEN_001, "cust-001-checking", limit=2)
    assert page1.page.next_offset is not None
    page2 = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", limit=2, page_key=page1.page.next_offset
    )
    assert page2.page.next_offset is not None
    assert page2.page.prev_offset is not None


async def test_get_transactions_pagination_last_page_has_no_next_offset() -> None:
    """The final page returns next_offset=None."""
    client = _client()
    # Walk to the last page.
    page_key: str | None = None
    last_result = None
    for _ in range(len(_ALL_TXNS) + 1):  # Safety limit.
        result = await client.get_transactions(
            _TOKEN_001, "cust-001-checking", limit=2, page_key=page_key
        )
        last_result = result
        if result.page.next_offset is None:
            break
        page_key = result.page.next_offset
    assert last_result is not None
    assert last_result.page.next_offset is None


async def test_get_transactions_pagination_cursor_past_end_returns_empty() -> None:
    """A cursor offset past the end of the result list returns empty items."""
    large_cursor = _encode_cursor(9999)
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001, "cust-001-checking", page_key=large_cursor
    )
    assert result.items == []


async def test_get_transactions_pagination_invalid_cursor_raises() -> None:
    """A malformed page_key raises InvalidPageCursorError."""
    client = _client()
    with pytest.raises(InvalidPageCursorError) as exc_info:
        await client.get_transactions(_TOKEN_001, "cust-001-checking", page_key="!!!bad!!!")
    assert exc_info.value.cursor == "!!!bad!!!"


async def test_get_transactions_pagination_total_stable_across_pages() -> None:
    """page.total is consistent (post-filter count) across all pages."""
    client = _client()
    page1 = await client.get_transactions(_TOKEN_001, "cust-001-checking", limit=2)
    total = page1.page.total
    assert total is not None
    page_key: str | None = page1.page.next_offset
    while page_key is not None:
        page = await client.get_transactions(
            _TOKEN_001, "cust-001-checking", limit=2, page_key=page_key
        )
        assert page.page.total == total
        page_key = page.page.next_offset


# ===========================================================================
# get_transactions — invalid date range
# ===========================================================================


async def test_get_transactions_invalid_date_range_raises() -> None:
    """start_time after end_time raises InvalidDateRangeError before any data access."""
    client = _client()
    with pytest.raises(InvalidDateRangeError) as exc_info:
        await client.get_transactions(
            _TOKEN_001,
            "cust-001-checking",
            start_time=_DEC_2025,
            end_time=_JAN_2025,
        )
    err = exc_info.value
    assert err.start_time == _DEC_2025
    assert err.end_time == _JAN_2025


async def test_get_transactions_equal_start_end_is_valid() -> None:
    """start_time == end_time is a valid (single-day) range — no error raised."""
    client = _client()
    result = await client.get_transactions(
        _TOKEN_001,
        "cust-001-checking",
        start_time=_JAN_2025,
        end_time=_JAN_2025,
    )
    assert isinstance(result.page.total, int)


async def test_get_transactions_invalid_date_range_audit_records_error() -> None:
    """An InvalidDateRangeError is captured by the audit trail as outcome=ERROR."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    with pytest.raises(InvalidDateRangeError):
        await client.get_transactions(
            _TOKEN_001,
            "cust-001-checking",
            start_time=_DEC_2025,
            end_time=_JAN_2025,
        )
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.outcome == AuditOutcome.ERROR
    assert event.error_type == "InvalidDateRangeError"


# ===========================================================================
# get_transactions — auth: not authorized
# ===========================================================================


async def test_get_transactions_unknown_token_raises_authentication_error() -> None:
    """An unknown bearer token raises AuthenticationError."""
    client = _client()
    with pytest.raises(AuthenticationError):
        await client.get_transactions(_TOKEN_UNKNOWN, "cust-001-checking")


async def test_get_transactions_expired_token_raises_authentication_error() -> None:
    """An expired bearer token raises AuthenticationError."""
    client = _client()
    with pytest.raises(AuthenticationError):
        await client.get_transactions(_TOKEN_EXPIRED, "cust-001-checking")


async def test_get_transactions_accounts_only_token_raises_authorization_error() -> None:
    """A token with only ACCOUNTS cluster raises AuthorizationError for TRANSACTIONS."""
    client = _client()
    with pytest.raises(AuthorizationError) as exc_info:
        await client.get_transactions(_TOKEN_ACCOUNTS_ONLY, "cust-001-checking")
    assert exc_info.value.cluster == "TRANSACTIONS"


async def test_get_transactions_cross_customer_account_raises_authorization_error() -> None:
    """Requesting an account belonging to a different customer raises AuthorizationError."""
    # tok_cust_001 is scoped to cust-001; cust-003-checking belongs to cust-003.
    client = _client()
    with pytest.raises(AuthorizationError) as exc_info:
        await client.get_transactions(_TOKEN_001, "cust-003-checking")
    assert exc_info.value.account_id == "cust-003-checking"


async def test_get_transactions_account_not_in_scope_raises_authorization_error() -> None:
    """An account the token does not cover raises AuthorizationError."""
    # tok_cust_003_txn_only covers only cust-003-checking, not cust-003-savings.
    client = _client()
    with pytest.raises(AuthorizationError):
        await client.get_transactions(_TOKEN_003_TXN_ONLY, "cust-003-savings")


# ===========================================================================
# get_transactions — audit: one event per call
# ===========================================================================


async def test_get_transactions_emits_exactly_one_audit_event_on_success() -> None:
    """A successful call emits exactly one audit event."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert len(sink.events) == 1


async def test_get_transactions_audit_event_action_is_get_transactions() -> None:
    """The audit event action field is 'get_transactions'."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert sink.events[0].action == "get_transactions"


async def test_get_transactions_audit_event_outcome_is_success() -> None:
    """A successful call records outcome=SUCCESS."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert sink.events[0].outcome == AuditOutcome.SUCCESS


async def test_get_transactions_audit_event_data_cluster_is_transactions() -> None:
    """The audit event resource.data_cluster is 'TRANSACTIONS'."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert sink.events[0].resource.data_cluster == "TRANSACTIONS"


async def test_get_transactions_audit_event_token_is_fingerprinted() -> None:
    """The audit event actor.token_id is the sha256 fingerprint, not the raw token."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert sink.events[0].actor.token_id.startswith("sha256:")
    assert _TOKEN_001 not in sink.events[0].actor.token_id


async def test_get_transactions_audit_event_account_id_in_resource() -> None:
    """The audit event resource.account_ids contains the requested account id."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_transactions(_TOKEN_001, "cust-001-checking")
    assert "cust-001-checking" in sink.events[0].resource.account_ids


async def test_get_transactions_auth_error_emits_error_audit_event() -> None:
    """An AuthorizationError is captured by the audit trail as outcome=ERROR."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    with pytest.raises(AuthorizationError):
        await client.get_transactions(_TOKEN_ACCOUNTS_ONLY, "cust-001-checking")
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.ERROR
    assert sink.events[0].error_type == "AuthorizationError"


async def test_get_transactions_multiple_calls_emit_one_event_each() -> None:
    """Each call emits exactly one event, no more."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_transactions(_TOKEN_001, "cust-001-checking")
    await client.get_transactions(_TOKEN_001, "cust-001-checking", limit=1)
    assert len(sink.events) == 2


# ===========================================================================
# FixtureTransactionDataSource — unit tests
# ===========================================================================


async def test_fixture_source_returns_transactions_for_known_account() -> None:
    """FixtureTransactionDataSource returns a non-empty list for a committed account."""
    source = FixtureTransactionDataSource(default_fixture_data_dir())
    txns = await source.list_transactions(
        token="tok", customer_id="cust-001", account_id="cust-001-checking"
    )
    assert len(txns) > 0
    assert all(isinstance(tx, Transaction) for tx in txns)


async def test_fixture_source_returns_empty_for_unknown_account() -> None:
    """FixtureTransactionDataSource returns [] for an account with no fixture file."""
    source = FixtureTransactionDataSource(default_fixture_data_dir())
    txns = await source.list_transactions(
        token="tok", customer_id="cust-999", account_id="no-such-account"
    )
    assert txns == []


async def test_fixture_source_caches_after_first_load() -> None:
    """The same list object is returned on repeated calls (in-memory cache)."""
    source = FixtureTransactionDataSource(default_fixture_data_dir())
    first = await source.list_transactions(
        token="tok", customer_id="cust-001", account_id="cust-001-checking"
    )
    second = await source.list_transactions(
        token="tok", customer_id="cust-001", account_id="cust-001-checking"
    )
    assert first is second


async def test_fixture_source_cust003_card_has_no_transactions() -> None:
    """Accounts that generated no transactions return an empty list from the fixture."""
    source = FixtureTransactionDataSource(default_fixture_data_dir())
    # cust-003-card.json exists but has total=0 — produced by the generator.
    txns = await source.list_transactions(
        token="tok", customer_id="cust-003", account_id="cust-003-card"
    )
    assert txns == []


# ===========================================================================
# Integration — 24-month pagination walk against committed fixtures
# ===========================================================================


async def test_integration_walk_full_24_month_window_cust003_checking() -> None:
    """Walk every page of cust-003-checking (813 txns) and verify the complete result set.

    Assertions:
    - Cumulative item count equals page.total on the first page.
    - next_offset chain terminates (no infinite loop).
    - All returned items are Transaction instances.
    - The final page has next_offset=None and prev_offset is set (not the first page).
    """
    client = default_transactions_client(trail=AuditTrail(sink=ListSink()))
    page_size = 100

    page_key: str | None = None
    all_items: list[Transaction] = []
    expected_total: int | None = None
    last_page = None

    for _ in range(1000):  # Safety limit — 813 / 100 = 9 pages.
        page = await client.get_transactions(
            _TOKEN_003, "cust-003-checking", limit=page_size, page_key=page_key
        )
        if expected_total is None:
            expected_total = page.page.total
        all_items.extend(page.items)
        last_page = page
        if page.page.next_offset is None:
            break
        page_key = page.page.next_offset

    assert expected_total is not None
    assert len(all_items) == expected_total
    assert all(isinstance(tx, Transaction) for tx in all_items)
    assert last_page is not None
    assert last_page.page.next_offset is None
    assert last_page.page.prev_offset is not None


async def test_integration_no_duplicates_across_pages_cust003_checking() -> None:
    """All transaction ids are unique across all pages (no overlap)."""
    client = default_transactions_client(trail=AuditTrail(sink=ListSink()))
    page_key: str | None = None
    seen_ids: set[str] = set()

    for _ in range(1000):
        page = await client.get_transactions(
            _TOKEN_003, "cust-003-checking", limit=100, page_key=page_key
        )
        for tx in page.items:
            assert tx.id not in seen_ids, f"Duplicate id: {tx.id}"
            seen_ids.add(tx.id)
        if page.page.next_offset is None:
            break
        page_key = page.page.next_offset


async def test_integration_date_filter_reduces_count_vs_unfiltered() -> None:
    """A narrower date window returns fewer transactions than the full 24-month set."""
    client = default_transactions_client(trail=AuditTrail(sink=ListSink()))

    all_page = await client.get_transactions(_TOKEN_003, "cust-003-checking", limit=1)
    filtered_page = await client.get_transactions(
        _TOKEN_003,
        "cust-003-checking",
        start_time=datetime(2025, 1, 1, tzinfo=UTC),
        end_time=datetime(2025, 6, 30, tzinfo=UTC),
        limit=1,
    )
    assert filtered_page.page.total is not None
    assert all_page.page.total is not None
    assert filtered_page.page.total < all_page.page.total


async def test_integration_cust003_has_pending_transactions_in_unfiltered() -> None:
    """cust-003-checking has PENDING transactions when no date/status filter is applied."""
    client = default_transactions_client(trail=AuditTrail(sink=ListSink()))
    # Walk all pages to collect pending — they're near the end of the 24-month window.
    page_key: str | None = None
    pending_found = False
    for _ in range(1000):
        page = await client.get_transactions(
            _TOKEN_003, "cust-003-checking", limit=100, page_key=page_key
        )
        if any(tx.status == TransactionStatus.PENDING for tx in page.items):
            pending_found = True
            break
        if page.page.next_offset is None:
            break
        page_key = page.page.next_offset
    assert pending_found, "Expected at least one PENDING transaction in cust-003-checking"


async def test_integration_posted_only_filter_excludes_pending() -> None:
    """status=POSTED on the full 24-month set contains no PENDING transactions."""
    client = default_transactions_client(trail=AuditTrail(sink=ListSink()))
    page_key: str | None = None
    for _ in range(1000):
        page = await client.get_transactions(
            _TOKEN_003,
            "cust-003-checking",
            status=TransactionStatus.POSTED,
            limit=100,
            page_key=page_key,
        )
        for tx in page.items:
            assert tx.status == TransactionStatus.POSTED
        if page.page.next_offset is None:
            break
        page_key = page.page.next_offset


async def test_integration_txn_only_token_can_paginate_full_window() -> None:
    """A TRANSACTIONS-only token can walk the full 24-month window."""
    client = default_transactions_client(trail=AuditTrail(sink=ListSink()))
    page = await client.get_transactions(
        _TOKEN_003_TXN_ONLY, "cust-003-checking", limit=50
    )
    assert page.page.total is not None
    assert page.page.total > 0
