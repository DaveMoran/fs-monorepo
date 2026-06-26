"""Tests for the async FDX account client.

Covers AccountsClient (get_accounts, get_account, get_balances), FixtureAccountDataSource,
pagination helpers, typed errors, audit one-event-per-call guarantee, and a real-wiring
integration smoke test against the committed fixtures + consents.json.

Test structure
--------------
- Hermetic unit tests use _FakeSource (in-memory, Protocol-compatible) + a real Authorizer
  over a _FakeResolver so the actual guard logic runs under controlled scopes.
- Audit assertions inject AuditTrail(sink=ListSink()) via AccountsClient(trail=...).
- The integration test at the bottom uses default_accounts_client() to exercise the full
  stack against committed fixture files.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from banking_client.auth import Authorizer, DataCluster
from banking_client.auth.resolver import ConsentResolver
from banking_client.auth.scope import ConsentScope
from banking_client.client import (
    AccountDataSource,
    AccountNotFoundError,
    AccountsClient,
    FixtureAccountDataSource,
    InvalidPageCursorError,
    default_accounts_client,
    default_fixture_data_dir,
)
from banking_client.client.accounts import _decode_cursor, _encode_cursor, _paginate
from banking_client.models.account import Account, Balance
from banking_client.models.enums import AccountStatus, AccountType, BalanceType
from banking_client.models.money import Money
from common.audit import AuditOutcome, AuditTrail, ListSink
from common.errors import AuthenticationError, AuthorizationError

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_TOKEN_001 = "tok_cust_001"
_TOKEN_002 = "tok_cust_002"
_TOKEN_001_EMPTY = "tok_cust_001_empty"
_TOKEN_001_GHOST = "tok_cust_001_ghost"
_TOKEN_003_TXN_ONLY = "tok_cust_003_txn_only"
_TOKEN_EXPIRED = "tok_expired"
_TOKEN_UNKNOWN = "tok_unknown"

_NOW_FIXED = datetime(2026, 1, 1, tzinfo=UTC)
_PAST = _NOW_FIXED - timedelta(days=1)


# ---------------------------------------------------------------------------
# In-memory consent resolver (controls scopes without touching the filesystem)
# ---------------------------------------------------------------------------


class _FakeResolver:
    """Minimal ConsentResolver satisfied by a static dict.

    Satisfies the ConsentResolver Protocol structurally — no inheritance needed.
    """

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
    """Build a ConsentScope with sensible defaults (ACCOUNTS + TRANSACTIONS)."""
    return ConsentScope(
        consent_id=f"consent-{customer_id}",
        customer_id=customer_id,
        account_ids=frozenset(account_ids),
        data_clusters=frozenset(clusters if clusters is not None else [DataCluster.ACCOUNTS, DataCluster.TRANSACTIONS]),
        expires_at=expires_at,
    )


_REGISTRY: dict[str, ConsentScope] = {
    _TOKEN_001: _scope(customer_id="cust-001", account_ids=["cust-001-checking"]),
    _TOKEN_002: _scope(customer_id="cust-002", account_ids=["cust-002-checking", "cust-002-savings", "cust-002-card"]),
    _TOKEN_001_EMPTY: _scope(customer_id="cust-001", account_ids=[], clusters=[DataCluster.ACCOUNTS]),
    _TOKEN_001_GHOST: _scope(customer_id="cust-001", account_ids=["cust-001-checking", "cust-001-ghost"]),
    _TOKEN_003_TXN_ONLY: _scope(
        customer_id="cust-003",
        account_ids=["cust-003-checking"],
        clusters=[DataCluster.TRANSACTIONS],
    ),
    _TOKEN_EXPIRED: _scope(
        customer_id="cust-002",
        account_ids=["cust-002-checking"],
        expires_at=_PAST,
    ),
}


# ---------------------------------------------------------------------------
# In-memory data source (Protocol-compatible; no filesystem)
# ---------------------------------------------------------------------------


def _money(value: str, currency: str = "USD") -> Money:
    """Build a Money instance."""
    return Money(value=Decimal(value), currency=currency)


def _balance(balance_type: BalanceType, value: str) -> Balance:
    """Build a Balance instance."""
    return Balance(
        balance_type=balance_type,
        amount=_money(value),
        as_of_date=_NOW_FIXED,
    )


def _account(
    account_id: str,
    account_type: AccountType = AccountType.CHECKING,
    balances: list[Balance] | None = None,
) -> Account:
    """Build a minimal Account instance."""
    return Account(
        id=account_id,
        account_type=account_type,
        account_number_display="****0000",
        status=AccountStatus.OPEN,
        currency="USD",
        balances=balances if balances is not None else [],
    )


_CUST_001_CHECKING = _account(
    "cust-001-checking",
    balances=[_balance(BalanceType.AVAILABLE, "1000.00"), _balance(BalanceType.CURRENT, "1100.00")],
)
_CUST_002_CHECKING = _account("cust-002-checking")
_CUST_002_SAVINGS = _account("cust-002-savings", account_type=AccountType.SAVINGS)
_CUST_002_CARD = _account("cust-002-card", account_type=AccountType.CREDIT_CARD)
_CUST_003_CHECKING = _account("cust-003-checking")


class _FakeSource:
    """In-memory AccountDataSource for unit tests.

    Satisfies AccountDataSource Protocol structurally.
    """

    def __init__(self, accounts: dict[str, list[Account]]) -> None:
        """Bind customer_id → account list."""
        self._accounts = accounts

    async def list_accounts(self, *, token: str, customer_id: str) -> list[Account]:
        """Return accounts for *customer_id*, or empty list."""
        return self._accounts.get(customer_id, [])

    async def get_account(self, *, token: str, customer_id: str, account_id: str) -> Account | None:
        """Return account by id within *customer_id*, or None."""
        for acct in self._accounts.get(customer_id, []):
            if acct.id == account_id:
                return acct
        return None


_DEFAULT_SOURCE = _FakeSource(
    {
        "cust-001": [_CUST_001_CHECKING],
        "cust-002": [_CUST_002_CHECKING, _CUST_002_SAVINGS, _CUST_002_CARD],
        "cust-003": [_CUST_003_CHECKING],
    }
)


# ---------------------------------------------------------------------------
# Client builder helpers
# ---------------------------------------------------------------------------


def _trail_and_sink() -> tuple[AuditTrail, ListSink]:
    """Return a fresh (AuditTrail, ListSink) pair for audit assertions."""
    sink = ListSink()
    return AuditTrail(sink=sink), sink


def _client(
    source: AccountDataSource | None = None,
    *,
    trail: AuditTrail | None = None,
    page_size: int = 25,
    registry: dict[str, ConsentScope] | None = None,
) -> AccountsClient:
    """Build an AccountsClient over the fake resolver + in-memory source.

    Always injects an AuditTrail(sink=ListSink()) when no trail is supplied so that
    tests never create a process-global StdoutJSONSink, which would interfere with
    capsys capture in test_audit.py::test_stdout_sink_emits_parseable_json.
    """
    resolver: ConsentResolver = _FakeResolver(registry if registry is not None else _REGISTRY)
    authorizer = Authorizer(resolver)
    effective_trail = trail if trail is not None else AuditTrail(sink=ListSink())
    return AccountsClient(
        data_source=source if source is not None else _DEFAULT_SOURCE,
        authorizer=authorizer,
        trail=effective_trail,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Pagination helpers (unit tests, no HTTP or auth)
# ---------------------------------------------------------------------------


def test_encode_decode_cursor_round_trips() -> None:
    """Encoding and decoding a cursor returns the original offset."""
    for offset in [0, 1, 10, 999]:
        assert _decode_cursor(_encode_cursor(offset), for_request="test") == offset


def test_decode_invalid_cursor_raises() -> None:
    """A non-base64 cursor raises InvalidPageCursorError."""
    with pytest.raises(InvalidPageCursorError) as exc_info:
        _decode_cursor("not-valid!!", for_request="get_accounts")
    assert exc_info.value.cursor == "not-valid!!"


def test_decode_negative_cursor_raises() -> None:
    """A cursor decoding to a negative integer raises InvalidPageCursorError."""
    neg_cursor = base64.urlsafe_b64encode(b"-1").decode().rstrip("=")
    with pytest.raises(InvalidPageCursorError):
        _decode_cursor(neg_cursor, for_request="get_accounts")


def test_paginate_first_page_no_next_when_all_fit() -> None:
    """Single-page result has no next_offset and prev_offset is None."""
    accounts = [_account(f"acct-{i:02d}") for i in range(3)]
    result = _paginate(accounts, limit=10, page_key=None)
    assert result.page.total == 3
    assert result.page.next_offset is None
    assert result.page.prev_offset is None
    assert len(result.items) == 3


def test_paginate_first_page_has_next_offset_when_more_exist() -> None:
    """First page has next_offset set and no prev_offset when items exceed limit."""
    accounts = [_account(f"acct-{i:02d}") for i in range(5)]
    result = _paginate(accounts, limit=2, page_key=None)
    assert result.page.total == 5
    assert result.page.next_offset is not None
    assert result.page.prev_offset is None
    assert len(result.items) == 2


def test_paginate_middle_page_has_both_offsets() -> None:
    """Middle page has both next_offset and prev_offset set."""
    accounts = [_account(f"acct-{i:02d}") for i in range(5)]
    # first page
    first = _paginate(accounts, limit=2, page_key=None)
    assert first.page.next_offset is not None
    # second page (middle)
    second = _paginate(accounts, limit=2, page_key=first.page.next_offset)
    assert second.page.next_offset is not None
    assert second.page.prev_offset is not None


def test_paginate_last_page_has_no_next_offset() -> None:
    """Last page has next_offset=None regardless of partial fill."""
    accounts = [_account(f"acct-{i:02d}") for i in range(3)]
    first = _paginate(accounts, limit=2, page_key=None)
    last = _paginate(accounts, limit=2, page_key=first.page.next_offset)
    assert len(last.items) == 1
    assert last.page.next_offset is None
    assert last.page.prev_offset is not None


def test_paginate_cursor_past_end_returns_empty_items() -> None:
    """A cursor pointing past the end returns an empty item list with total still set."""
    accounts = [_account(f"acct-{i:02d}") for i in range(2)]
    cursor = _encode_cursor(100)
    result = _paginate(accounts, limit=10, page_key=cursor)
    assert result.items == []
    assert result.page.total == 2
    assert result.page.next_offset is None


def test_paginate_invalid_cursor_raises() -> None:
    """_paginate propagates InvalidPageCursorError from a malformed page_key."""
    accounts = [_account("acct-00")]
    with pytest.raises(InvalidPageCursorError):
        _paginate(accounts, limit=5, page_key="!!!bad!!!")


def test_paginate_empty_list() -> None:
    """Paginating an empty list returns total=0 and no items or offsets."""
    result = _paginate([], limit=10, page_key=None)
    assert result.page.total == 0
    assert result.items == []
    assert result.page.next_offset is None
    assert result.page.prev_offset is None


# ---------------------------------------------------------------------------
# get_accounts — happy path
# ---------------------------------------------------------------------------


async def test_get_accounts_returns_authorized_accounts() -> None:
    """get_accounts returns exactly the accounts listed in the consent scope."""
    client = _client()
    page = await client.get_accounts(_TOKEN_002)
    account_ids = {a.id for a in page.items}
    assert account_ids == {"cust-002-checking", "cust-002-savings", "cust-002-card"}


async def test_get_accounts_accounts_sorted_by_id() -> None:
    """get_accounts returns accounts in deterministic (ascending account id) order."""
    client = _client()
    page = await client.get_accounts(_TOKEN_002)
    ids = [a.id for a in page.items]
    assert ids == sorted(ids)


async def test_get_accounts_total_reflects_full_count() -> None:
    """PageMetadata.total equals the number of authorized accounts before pagination."""
    client = _client()
    page = await client.get_accounts(_TOKEN_002, limit=1)
    assert page.page.total == 3


async def test_get_accounts_single_account() -> None:
    """get_accounts returns a single-item page for a single-account scope."""
    client = _client()
    page = await client.get_accounts(_TOKEN_001)
    assert len(page.items) == 1
    assert page.items[0].id == "cust-001-checking"


async def test_get_accounts_empty_scope_returns_empty_page() -> None:
    """get_accounts returns an empty page when the consent scope grants no account ids."""
    client = _client()
    page = await client.get_accounts(_TOKEN_001_EMPTY)
    assert page.items == []
    assert page.page.total == 0
    assert page.page.next_offset is None


# ---------------------------------------------------------------------------
# get_accounts — pagination boundary
# ---------------------------------------------------------------------------


async def test_get_accounts_pagination_first_page() -> None:
    """limit=1 returns one account and sets next_offset but no prev_offset."""
    client = _client()
    page = await client.get_accounts(_TOKEN_002, limit=1)
    assert len(page.items) == 1
    assert page.page.next_offset is not None
    assert page.page.prev_offset is None


async def test_get_accounts_pagination_second_page() -> None:
    """Following next_offset yields the next account and has both offsets."""
    client = _client()
    p1 = await client.get_accounts(_TOKEN_002, limit=1)
    assert p1.page.next_offset is not None
    p2 = await client.get_accounts(_TOKEN_002, limit=1, page_key=p1.page.next_offset)
    assert len(p2.items) == 1
    assert p2.items[0].id != p1.items[0].id
    assert p2.page.next_offset is not None
    assert p2.page.prev_offset is not None


async def test_get_accounts_pagination_last_page_no_next_offset() -> None:
    """limit=all-at-once returns next_offset=None."""
    client = _client()
    page = await client.get_accounts(_TOKEN_002, limit=10)
    assert page.page.next_offset is None
    assert len(page.items) == 3


async def test_get_accounts_bad_cursor_raises() -> None:
    """A malformed page_key raises InvalidPageCursorError."""
    client = _client()
    with pytest.raises(InvalidPageCursorError):
        await client.get_accounts(_TOKEN_002, limit=2, page_key="!!bad!!")


# ---------------------------------------------------------------------------
# get_account — happy path
# ---------------------------------------------------------------------------


async def test_get_account_returns_correct_account() -> None:
    """get_account returns the exact account requested when it is in scope."""
    client = _client()
    account = await client.get_account(_TOKEN_001, "cust-001-checking")
    assert account.id == "cust-001-checking"
    assert account.account_type == AccountType.CHECKING


# ---------------------------------------------------------------------------
# get_balances — happy path
# ---------------------------------------------------------------------------


async def test_get_balances_returns_embedded_balances() -> None:
    """get_balances returns the Balance list embedded in the account."""
    client = _client()
    balances = await client.get_balances(_TOKEN_001, "cust-001-checking")
    assert len(balances) == 2
    types = {b.balance_type for b in balances}
    assert types == {BalanceType.AVAILABLE, BalanceType.CURRENT}


async def test_get_balances_values_are_exact_decimals() -> None:
    """Balance amounts preserve Decimal precision (no float rounding)."""
    client = _client()
    balances = await client.get_balances(_TOKEN_001, "cust-001-checking")
    by_type = {b.balance_type: b.amount.value for b in balances}
    assert by_type[BalanceType.AVAILABLE] == Decimal("1000.00")
    assert by_type[BalanceType.CURRENT] == Decimal("1100.00")


async def test_get_balances_empty_when_account_has_none() -> None:
    """get_balances returns an empty list for an account with no balance entries."""
    client = _client()
    balances = await client.get_balances(_TOKEN_002, "cust-002-checking")
    assert balances == []


# ---------------------------------------------------------------------------
# Not-authorized (customer B's account)
# ---------------------------------------------------------------------------


async def test_get_account_cross_customer_raises_authorization_error() -> None:
    """get_account raises AuthorizationError when requesting another customer's account."""
    client = _client()
    with pytest.raises(AuthorizationError) as exc_info:
        await client.get_account(_TOKEN_001, "cust-002-checking")
    assert exc_info.value.account_id == "cust-002-checking"


async def test_get_balances_cross_customer_raises_authorization_error() -> None:
    """get_balances raises AuthorizationError when the account is outside the scope."""
    client = _client()
    with pytest.raises(AuthorizationError):
        await client.get_balances(_TOKEN_001, "cust-002-checking")


async def test_get_accounts_cluster_denial_raises_authorization_error() -> None:
    """get_accounts raises AuthorizationError when ACCOUNTS cluster is not granted."""
    client = _client()
    with pytest.raises(AuthorizationError) as exc_info:
        await client.get_accounts(_TOKEN_003_TXN_ONLY)
    assert exc_info.value.cluster == "ACCOUNTS"


# ---------------------------------------------------------------------------
# Not-found (authorized but absent from data source)
# ---------------------------------------------------------------------------


async def test_get_account_not_found_raises_account_not_found_error() -> None:
    """get_account raises AccountNotFoundError when the id is in scope but not in the source."""
    client = _client()
    with pytest.raises(AccountNotFoundError) as exc_info:
        await client.get_account(_TOKEN_001_GHOST, "cust-001-ghost")
    assert exc_info.value.account_id == "cust-001-ghost"


async def test_get_balances_not_found_raises_account_not_found_error() -> None:
    """get_balances raises AccountNotFoundError for a scope-authorized but absent account."""
    client = _client()
    with pytest.raises(AccountNotFoundError):
        await client.get_balances(_TOKEN_001_GHOST, "cust-001-ghost")


# ---------------------------------------------------------------------------
# Unknown / expired token
# ---------------------------------------------------------------------------


async def test_get_accounts_unknown_token_raises_authentication_error() -> None:
    """get_accounts raises AuthenticationError for an unrecognised token."""
    client = _client()
    with pytest.raises(AuthenticationError):
        await client.get_accounts(_TOKEN_UNKNOWN)


async def test_get_account_unknown_token_raises_authentication_error() -> None:
    """get_account raises AuthenticationError for an unrecognised token."""
    client = _client()
    with pytest.raises(AuthenticationError):
        await client.get_account(_TOKEN_UNKNOWN, "cust-001-checking")


async def test_get_accounts_expired_token_raises_authentication_error() -> None:
    """get_accounts raises AuthenticationError for an expired token."""
    client = _client()
    with pytest.raises(AuthenticationError):
        await client.get_accounts(_TOKEN_EXPIRED)


# ---------------------------------------------------------------------------
# Audit: one event per call, correct fields, token redacted
# ---------------------------------------------------------------------------


async def test_get_accounts_emits_exactly_one_success_event() -> None:
    """get_accounts emits exactly one SUCCESS audit event per call."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_accounts(_TOKEN_001)
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.SUCCESS


async def test_get_accounts_event_has_correct_action_and_cluster() -> None:
    """get_accounts audit event has action='get_accounts' and data_cluster='ACCOUNTS'."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_accounts(_TOKEN_001)
    event = sink.events[0]
    assert event.action == "get_accounts"
    assert event.resource.data_cluster == "ACCOUNTS"


async def test_get_account_emits_exactly_one_success_event() -> None:
    """get_account emits exactly one SUCCESS audit event per call."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_account(_TOKEN_001, "cust-001-checking")
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.SUCCESS


async def test_get_balances_emits_exactly_one_event_not_two() -> None:
    """get_balances emits one event per call (does not call the audited get_account)."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_balances(_TOKEN_001, "cust-001-checking")
    assert len(sink.events) == 1
    assert sink.events[0].action == "get_balances"


async def test_get_accounts_token_fingerprint_not_raw_token() -> None:
    """The audit event actor.token_id is a sha256 fingerprint, never the raw token."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_accounts(_TOKEN_001)
    token_id = sink.events[0].actor.token_id
    assert token_id.startswith("sha256:")
    assert _TOKEN_001 not in token_id


async def test_error_emits_one_error_event_with_error_type() -> None:
    """A failed call emits exactly one ERROR event with the exception class name."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    with pytest.raises(AuthorizationError):
        await client.get_account(_TOKEN_001, "cust-002-checking")
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.ERROR
    assert sink.events[0].error_type == "AuthorizationError"


async def test_not_found_emits_error_event_with_error_type() -> None:
    """AccountNotFoundError is captured in the audit event with the right error_type."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    with pytest.raises(AccountNotFoundError):
        await client.get_account(_TOKEN_001_GHOST, "cust-001-ghost")
    assert len(sink.events) == 1
    assert sink.events[0].error_type == "AccountNotFoundError"


async def test_result_count_none_for_get_accounts() -> None:
    """get_accounts result_count is None because PaginatedResponse has no __len__."""
    # The @audited decorator calls len(result) and suppresses TypeError; since
    # PaginatedResponse is a Pydantic BaseModel without __len__, result_count stays None.
    # Callers use page.page.total for count information instead.
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    await client.get_accounts(_TOKEN_002)
    assert sink.events[0].result_count is None


async def test_result_count_set_on_get_balances() -> None:
    """get_balances result_count is set because list[Balance] supports __len__."""
    trail, sink = _trail_and_sink()
    client = _client(trail=trail)
    balances = await client.get_balances(_TOKEN_001, "cust-001-checking")
    assert sink.events[0].result_count == len(balances)


# ---------------------------------------------------------------------------
# FixtureAccountDataSource unit tests
# ---------------------------------------------------------------------------


def _fixture_source() -> FixtureAccountDataSource:
    """Return a FixtureAccountDataSource over the committed fixture data."""
    return FixtureAccountDataSource(default_fixture_data_dir())


async def test_fixture_source_lists_accounts_for_cust_002() -> None:
    """FixtureAccountDataSource returns all three cust-002 accounts from committed JSON."""
    source = _fixture_source()
    accounts = await source.list_accounts(token=_TOKEN_002, customer_id="cust-002")
    ids = {a.id for a in accounts}
    assert ids == {"cust-002-checking", "cust-002-savings", "cust-002-card"}


async def test_fixture_source_get_account_returns_correct_entry() -> None:
    """FixtureAccountDataSource.get_account returns the matching account by id."""
    source = _fixture_source()
    account = await source.get_account(token=_TOKEN_002, customer_id="cust-002", account_id="cust-002-savings")
    assert account is not None
    assert account.id == "cust-002-savings"
    assert account.account_type == AccountType.SAVINGS


async def test_fixture_source_get_account_unknown_returns_none() -> None:
    """FixtureAccountDataSource.get_account returns None for an unknown account id."""
    source = _fixture_source()
    result = await source.get_account(token=_TOKEN_002, customer_id="cust-002", account_id="cust-002-nonexistent")
    assert result is None


async def test_fixture_source_unknown_customer_returns_empty() -> None:
    """FixtureAccountDataSource returns an empty list for an unknown customer."""
    source = _fixture_source()
    accounts = await source.list_accounts(token="tok", customer_id="cust-999")
    assert accounts == []


async def test_fixture_source_caches_customer_file() -> None:
    """FixtureAccountDataSource reads each customer file at most once (caching)."""
    source = _fixture_source()
    a1 = await source.list_accounts(token=_TOKEN_001, customer_id="cust-001")
    a2 = await source.list_accounts(token=_TOKEN_001, customer_id="cust-001")
    # Same objects returned — identity check proves cache was hit.
    assert a1 is a2


async def test_fixture_source_account_balances_populated() -> None:
    """FixtureAccountDataSource returns accounts with non-empty Balance lists."""
    source = _fixture_source()
    account = await source.get_account(token=_TOKEN_002, customer_id="cust-002", account_id="cust-002-checking")
    assert account is not None
    assert len(account.balances) > 0
    balance_types = {b.balance_type for b in account.balances}
    # FDX fixture always emits AVAILABLE + CURRENT.
    assert BalanceType.AVAILABLE in balance_types
    assert BalanceType.CURRENT in balance_types


# ---------------------------------------------------------------------------
# AccountDataSource Protocol structural check
# ---------------------------------------------------------------------------


def test_fake_source_satisfies_protocol() -> None:
    """_FakeSource satisfies the AccountDataSource Protocol structurally."""

    def _accepts_source(s: AccountDataSource) -> None:  # pragma: no cover
        pass

    _accepts_source(_DEFAULT_SOURCE)  # type checker validates this; no assert needed at runtime


# ---------------------------------------------------------------------------
# Real-wiring integration test (committed fixtures/data + consents.json)
# ---------------------------------------------------------------------------
#
# These tests use default_accounts_client(trail=...) with an injected ListSink to avoid
# creating a process-global StdoutJSONSink that would interfere with capsys capture in
# test_audit.py::test_stdout_sink_emits_parseable_json.  The real wiring (FixtureAccountDataSource
# + default_authorizer over committed consents.json) is still fully exercised.


def _default_client() -> tuple[AccountsClient, ListSink]:
    """Return a default_accounts_client with an injected ListSink for the test suite."""
    sink = ListSink()
    client = default_accounts_client(trail=AuditTrail(sink=sink))
    return client, sink


async def test_default_client_get_accounts_cust_002() -> None:
    """default_accounts_client().get_accounts returns the 3 real cust-002 accounts."""
    client, _ = _default_client()
    page = await client.get_accounts("tok_cust_002")
    ids = {a.id for a in page.items}
    assert ids == {"cust-002-checking", "cust-002-savings", "cust-002-card"}
    assert page.page.total == 3


async def test_default_client_get_account_cust_002_checking() -> None:
    """default_accounts_client().get_account returns the correct account from fixtures."""
    client, _ = _default_client()
    account = await client.get_account("tok_cust_002", "cust-002-checking")
    assert account.id == "cust-002-checking"
    assert account.account_type == AccountType.CHECKING
    assert account.status == AccountStatus.OPEN


async def test_default_client_get_balances_cust_002_checking() -> None:
    """default_accounts_client().get_balances returns real balance data from fixtures."""
    client, _ = _default_client()
    balances = await client.get_balances("tok_cust_002", "cust-002-checking")
    assert len(balances) == 2
    types = {b.balance_type for b in balances}
    assert types == {BalanceType.AVAILABLE, BalanceType.CURRENT}
    # Fixture balance values are exact Decimals — verify they're positive and sane.
    for b in balances:
        assert b.amount.value > Decimal("0")


async def test_default_client_cust_001_single_account() -> None:
    """default_accounts_client() with tok_cust_001 yields exactly 1 account."""
    client, _ = _default_client()
    page = await client.get_accounts("tok_cust_001")
    assert len(page.items) == 1
    assert page.items[0].id == "cust-001-checking"


async def test_default_client_cross_customer_raises() -> None:
    """default_accounts_client() raises AuthorizationError for a cross-customer account."""
    client, _ = _default_client()
    with pytest.raises(AuthorizationError):
        await client.get_account("tok_cust_001", "cust-002-checking")


async def test_default_client_expired_token_raises() -> None:
    """default_accounts_client() raises AuthenticationError for the expired test token."""
    client, _ = _default_client()
    with pytest.raises(AuthenticationError):
        await client.get_accounts("tok_expired")


async def test_default_client_consents_json_parses_correctly() -> None:
    """The committed consents.json parses without error as a ConsentRegistry."""
    from banking_client.auth import ConsentRegistry
    from banking_client.auth.resolver import default_consent_path

    path = default_consent_path()
    registry = ConsentRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    # Confirm our test tokens are present.
    assert "tok_cust_001" in registry.root
    assert "tok_cust_002" in registry.root
    assert "tok_expired" in registry.root
    # Confirm the expired token really has an expiry in the past.
    expired_scope = registry.root["tok_expired"]
    assert expired_scope.expires_at is not None
    assert expired_scope.expires_at < datetime.now(UTC)
