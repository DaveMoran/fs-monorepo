"""Tests for the auth + consent boundary.

Exercises DataCluster, ConsentScope (including frozen-model immutability and sorted
serialization), the ConsentResolver Protocol, FixtureConsentResolver (happy path, unknown
token, expired token), and Authorizer (happy path, account out of scope, cluster out of
scope, cross-customer isolation).

Three synthetic consent scopes mirror the planned fixture archetypes:
- cust-001: single checking account, ACCOUNTS + TRANSACTIONS.
- cust-002: checking + savings + card, ACCOUNTS + TRANSACTIONS.
- cust-003 (NARROW): checking + savings only, ACCOUNTS + TRANSACTIONS — excludes the
  card, the retirement/INVESTMENT account, and the INVESTMENTS cluster.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from banking_client.auth import (
    Authorizer,
    ConsentRegistry,
    ConsentResolver,
    ConsentScope,
    DataCluster,
    FixtureConsentResolver,
    default_consent_path,
)
from common.errors import AuthenticationError, AuthorizationError

# ---------------------------------------------------------------------------
# Module-level scope constants (mirrors the planned consents.json archetypes)
# ---------------------------------------------------------------------------

_TOKEN_001 = "tok_cust_001"
_TOKEN_002 = "tok_cust_002"
_TOKEN_003 = "tok_cust_003"
_TOKEN_UNKNOWN = "tok_unknown"

_SCOPE_001 = ConsentScope(
    consent_id="consent-001",
    customer_id="cust-001",
    account_ids=frozenset(["cust-001-checking"]),
    data_clusters=frozenset([DataCluster.ACCOUNTS, DataCluster.TRANSACTIONS]),
)

_SCOPE_002 = ConsentScope(
    consent_id="consent-002",
    customer_id="cust-002",
    account_ids=frozenset(["cust-002-checking", "cust-002-savings", "cust-002-card"]),
    data_clusters=frozenset([DataCluster.ACCOUNTS, DataCluster.TRANSACTIONS]),
)

_SCOPE_003_NARROW = ConsentScope(
    consent_id="consent-003",
    customer_id="cust-003",
    # Deliberately excludes cust-003-card and cust-003-retirement.
    account_ids=frozenset(["cust-003-checking", "cust-003-savings"]),
    # Deliberately excludes DataCluster.INVESTMENTS.
    data_clusters=frozenset([DataCluster.ACCOUNTS, DataCluster.TRANSACTIONS]),
)

_DEFAULT_REGISTRY: dict[str, ConsentScope] = {
    _TOKEN_001: _SCOPE_001,
    _TOKEN_002: _SCOPE_002,
    _TOKEN_003: _SCOPE_003_NARROW,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_registry(tmp_path: Path, entries: dict[str, ConsentScope] | None = None) -> Path:
    """Write a consents.json to tmp_path and return its path."""
    path = tmp_path / "consents.json"
    registry = ConsentRegistry(root=entries if entries is not None else _DEFAULT_REGISTRY)
    path.write_text(registry.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8")
    return path


def _resolver(tmp_path: Path, now: datetime | None = None) -> FixtureConsentResolver:
    """Build a FixtureConsentResolver backed by the default test registry."""
    path = _write_registry(tmp_path)
    if now is not None:
        fixed = now
        return FixtureConsentResolver(path, now=lambda: fixed)
    return FixtureConsentResolver(path)


def _authorizer(tmp_path: Path) -> Authorizer:
    """Build an Authorizer backed by the default test registry."""
    return Authorizer(_resolver(tmp_path))


# ---------------------------------------------------------------------------
# DataCluster
# ---------------------------------------------------------------------------


def test_data_cluster_values() -> None:
    """DataCluster members are StrEnum values that compare equal to their strings."""
    assert DataCluster.ACCOUNTS == "ACCOUNTS"
    assert DataCluster.TRANSACTIONS == "TRANSACTIONS"
    assert DataCluster.INVESTMENTS == "INVESTMENTS"


def test_data_cluster_membership() -> None:
    """DataCluster supports 'in' checks against a frozenset of clusters."""
    granted: frozenset[DataCluster] = frozenset([DataCluster.ACCOUNTS, DataCluster.TRANSACTIONS])
    assert DataCluster.ACCOUNTS in granted
    assert DataCluster.INVESTMENTS not in granted


# ---------------------------------------------------------------------------
# ConsentScope construction and model properties
# ---------------------------------------------------------------------------


def test_consent_scope_constructs() -> None:
    """ConsentScope builds from snake_case field names with frozenset membership."""
    scope = _SCOPE_001
    assert scope.consent_id == "consent-001"
    assert scope.customer_id == "cust-001"
    assert "cust-001-checking" in scope.account_ids
    assert DataCluster.ACCOUNTS in scope.data_clusters
    assert scope.expires_at is None


def test_consent_scope_accepts_camel_case_aliases() -> None:
    """ConsentScope can be constructed from camelCase keys (FDX wire format)."""
    scope = ConsentScope.model_validate(
        {
            "consentId": "c-x",
            "customerId": "cust-x",
            "accountIds": ["acct-x"],
            "dataClusters": ["ACCOUNTS"],
        }
    )
    assert scope.consent_id == "c-x"
    assert scope.customer_id == "cust-x"


def test_consent_scope_is_frozen() -> None:
    """Mutating a ConsentScope raises ValidationError (frozen model)."""
    scope = _SCOPE_001
    with pytest.raises(ValidationError):
        scope.customer_id = "cust-999"  # type: ignore[misc]


def test_consent_scope_serializes_account_ids_sorted() -> None:
    """account_ids serialize as a sorted list for byte-stable JSON output."""
    scope = ConsentScope(
        consent_id="c-1",
        customer_id="cust-1",
        account_ids=frozenset(["cust-1-savings", "cust-1-checking", "cust-1-card"]),
        data_clusters=frozenset([DataCluster.ACCOUNTS]),
    )
    data = json.loads(scope.model_dump_json(by_alias=True))
    assert data["accountIds"] == ["cust-1-card", "cust-1-checking", "cust-1-savings"]


def test_consent_scope_serializes_clusters_sorted() -> None:
    """data_clusters serialize as a sorted list for byte-stable JSON output."""
    scope = ConsentScope(
        consent_id="c-1",
        customer_id="cust-1",
        account_ids=frozenset(["cust-1-checking"]),
        data_clusters=frozenset([DataCluster.TRANSACTIONS, DataCluster.ACCOUNTS]),
    )
    data = json.loads(scope.model_dump_json(by_alias=True))
    assert data["dataClusters"] == ["ACCOUNTS", "TRANSACTIONS"]


def test_consent_scope_with_expiry() -> None:
    """ConsentScope stores expires_at as a UTC-aware datetime."""
    expiry = datetime(2026, 12, 31, tzinfo=UTC)
    scope = ConsentScope(
        consent_id="c-exp",
        customer_id="cust-exp",
        account_ids=frozenset(["acct-exp"]),
        data_clusters=frozenset([DataCluster.ACCOUNTS]),
        expires_at=expiry,
    )
    assert scope.expires_at == expiry


# ---------------------------------------------------------------------------
# ConsentRegistry round-trip
# ---------------------------------------------------------------------------


def test_registry_round_trips_via_json(tmp_path: Path) -> None:
    """ConsentRegistry serializes and re-parses without data loss."""
    path = _write_registry(tmp_path)
    reloaded = ConsentRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    assert reloaded.root.keys() == _DEFAULT_REGISTRY.keys()
    assert reloaded.root[_TOKEN_001].customer_id == "cust-001"
    assert reloaded.root[_TOKEN_003].customer_id == "cust-003"


def test_registry_json_uses_camel_case(tmp_path: Path) -> None:
    """consents.json uses camelCase keys matching the FDX wire format."""
    path = _write_registry(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    scope_json = raw[_TOKEN_001]
    assert "consentId" in scope_json
    assert "customerId" in scope_json
    assert "accountIds" in scope_json
    assert "dataClusters" in scope_json
    assert "consent_id" not in scope_json


# ---------------------------------------------------------------------------
# ConsentResolver protocol structural check
# ---------------------------------------------------------------------------


def test_fixture_resolver_satisfies_protocol(tmp_path: Path) -> None:
    """FixtureConsentResolver is assignable to ConsentResolver without inheritance."""
    resolver: ConsentResolver = _resolver(tmp_path)
    scope = resolver.resolve(_TOKEN_001)
    assert scope.customer_id == "cust-001"


# ---------------------------------------------------------------------------
# FixtureConsentResolver — happy paths
# ---------------------------------------------------------------------------


def test_resolve_cust_001(tmp_path: Path) -> None:
    """Resolving tok_cust_001 returns the single-account cust-001 scope."""
    scope = _resolver(tmp_path).resolve(_TOKEN_001)
    assert scope.customer_id == "cust-001"
    assert scope.account_ids == frozenset(["cust-001-checking"])
    assert DataCluster.ACCOUNTS in scope.data_clusters
    assert DataCluster.TRANSACTIONS in scope.data_clusters


def test_resolve_cust_002_multi_account(tmp_path: Path) -> None:
    """Resolving tok_cust_002 returns all three cust-002 accounts in scope."""
    scope = _resolver(tmp_path).resolve(_TOKEN_002)
    assert scope.customer_id == "cust-002"
    assert "cust-002-checking" in scope.account_ids
    assert "cust-002-savings" in scope.account_ids
    assert "cust-002-card" in scope.account_ids


def test_resolve_cust_003_narrow(tmp_path: Path) -> None:
    """Resolving tok_cust_003 returns the narrow scope (checking + savings only)."""
    scope = _resolver(tmp_path).resolve(_TOKEN_003)
    assert scope.customer_id == "cust-003"
    assert "cust-003-checking" in scope.account_ids
    assert "cust-003-savings" in scope.account_ids
    assert "cust-003-card" not in scope.account_ids
    assert "cust-003-retirement" not in scope.account_ids
    assert DataCluster.INVESTMENTS not in scope.data_clusters


# ---------------------------------------------------------------------------
# FixtureConsentResolver — failure paths
# ---------------------------------------------------------------------------


def test_resolve_unknown_token_raises(tmp_path: Path) -> None:
    """Resolving an unrecognised token raises AuthenticationError."""
    with pytest.raises(AuthenticationError):
        _resolver(tmp_path).resolve(_TOKEN_UNKNOWN)


def test_resolve_expired_token_raises(tmp_path: Path) -> None:
    """Resolving a token whose expires_at is in the past raises AuthenticationError."""
    expiry = datetime(2025, 1, 1, tzinfo=UTC)
    expired_scope = ConsentScope(
        consent_id="c-exp",
        customer_id="cust-exp",
        account_ids=frozenset(["acct-exp"]),
        data_clusters=frozenset([DataCluster.ACCOUNTS]),
        expires_at=expiry,
    )
    path = _write_registry(tmp_path, {"tok_expired": expired_scope})
    # Inject a 'now' that is after the expiry to guarantee the token is expired.
    now = datetime(2025, 6, 1, tzinfo=UTC)
    resolver = FixtureConsentResolver(path, now=lambda: now)
    with pytest.raises(AuthenticationError):
        resolver.resolve("tok_expired")


def test_resolve_not_yet_expired_succeeds(tmp_path: Path) -> None:
    """Resolving a token whose expires_at is in the future succeeds."""
    expiry = datetime(2027, 1, 1, tzinfo=UTC)
    future_scope = ConsentScope(
        consent_id="c-future",
        customer_id="cust-future",
        account_ids=frozenset(["acct-future"]),
        data_clusters=frozenset([DataCluster.ACCOUNTS]),
        expires_at=expiry,
    )
    path = _write_registry(tmp_path, {"tok_future": future_scope})
    now = datetime(2026, 6, 1, tzinfo=UTC)
    resolver = FixtureConsentResolver(path, now=lambda: now)
    scope = resolver.resolve("tok_future")
    assert scope.customer_id == "cust-future"


def test_resolve_at_exact_expiry_raises(tmp_path: Path) -> None:
    """Resolving a token at exactly expires_at (>= boundary) raises AuthenticationError."""
    expiry = datetime(2026, 6, 1, tzinfo=UTC)
    expiring_scope = ConsentScope(
        consent_id="c-exact",
        customer_id="cust-exact",
        account_ids=frozenset(["acct-exact"]),
        data_clusters=frozenset([DataCluster.ACCOUNTS]),
        expires_at=expiry,
    )
    path = _write_registry(tmp_path, {"tok_exact": expiring_scope})
    resolver = FixtureConsentResolver(path, now=lambda: expiry)
    with pytest.raises(AuthenticationError):
        resolver.resolve("tok_exact")


# ---------------------------------------------------------------------------
# Authorizer — happy paths
# ---------------------------------------------------------------------------


def test_authorize_cust_001_checking_accounts(tmp_path: Path) -> None:
    """cust-001 token authorises cust-001-checking for ACCOUNTS; returns trusted scope."""
    scope = _authorizer(tmp_path).authorize(_TOKEN_001, "cust-001-checking", DataCluster.ACCOUNTS)
    assert scope.customer_id == "cust-001"


def test_authorize_cust_001_checking_transactions(tmp_path: Path) -> None:
    """cust-001 token authorises cust-001-checking for TRANSACTIONS."""
    scope = _authorizer(tmp_path).authorize(_TOKEN_001, "cust-001-checking", DataCluster.TRANSACTIONS)
    assert scope.customer_id == "cust-001"


def test_authorize_cust_002_all_accounts_and_clusters(tmp_path: Path) -> None:
    """cust-002 token authorises all three accounts for both granted clusters."""
    auth = _authorizer(tmp_path)
    for account_id in ("cust-002-checking", "cust-002-savings", "cust-002-card"):
        for cluster in (DataCluster.ACCOUNTS, DataCluster.TRANSACTIONS):
            scope = auth.authorize(_TOKEN_002, account_id, cluster)
            assert scope.customer_id == "cust-002"


def test_authorize_cust_003_narrow_allowed(tmp_path: Path) -> None:
    """cust-003 narrow token allows checking and savings for granted clusters."""
    auth = _authorizer(tmp_path)
    for account_id in ("cust-003-checking", "cust-003-savings"):
        for cluster in (DataCluster.ACCOUNTS, DataCluster.TRANSACTIONS):
            scope = auth.authorize(_TOKEN_003, account_id, cluster)
            assert scope.customer_id == "cust-003"


# ---------------------------------------------------------------------------
# Authorizer — rejection paths
# ---------------------------------------------------------------------------


def test_authorize_account_out_of_scope_raises(tmp_path: Path) -> None:
    """Requesting cust-003-retirement (not in narrow scope) raises AuthorizationError."""
    with pytest.raises(AuthorizationError) as exc_info:
        _authorizer(tmp_path).authorize(_TOKEN_003, "cust-003-retirement", DataCluster.ACCOUNTS)
    err = exc_info.value
    assert err.customer_id == "cust-003"
    assert err.account_id == "cust-003-retirement"
    assert "account not in consent scope" in err.reason


def test_authorize_card_out_of_narrow_scope_raises(tmp_path: Path) -> None:
    """Requesting cust-003-card (excluded by narrow scope) raises AuthorizationError."""
    with pytest.raises(AuthorizationError):
        _authorizer(tmp_path).authorize(_TOKEN_003, "cust-003-card", DataCluster.ACCOUNTS)


def test_authorize_cluster_out_of_scope_raises(tmp_path: Path) -> None:
    """Requesting INVESTMENTS (not granted) raises AuthorizationError for cust-003."""
    with pytest.raises(AuthorizationError) as exc_info:
        _authorizer(tmp_path).authorize(_TOKEN_003, "cust-003-checking", DataCluster.INVESTMENTS)
    err = exc_info.value
    assert err.customer_id == "cust-003"
    assert err.cluster == "INVESTMENTS"
    assert "data cluster not in consent scope" in err.reason


def test_authorize_cross_customer_isolation(tmp_path: Path) -> None:
    """cust-001 token cannot access cust-002-checking (cross-customer rejection)."""
    with pytest.raises(AuthorizationError) as exc_info:
        _authorizer(tmp_path).authorize(_TOKEN_001, "cust-002-checking", DataCluster.ACCOUNTS)
    err = exc_info.value
    # The scope's customer_id is cust-001 — the token belongs to them, not cust-002.
    assert err.customer_id == "cust-001"
    assert err.account_id == "cust-002-checking"


def test_authorize_unknown_token_raises_authentication_error(tmp_path: Path) -> None:
    """Unknown token raises AuthenticationError before any scope check."""
    with pytest.raises(AuthenticationError):
        _authorizer(tmp_path).authorize(_TOKEN_UNKNOWN, "cust-001-checking", DataCluster.ACCOUNTS)


# ---------------------------------------------------------------------------
# AuthorizationError attributes
# ---------------------------------------------------------------------------


def test_authorization_error_attributes() -> None:
    """AuthorizationError stores customer_id, reason, account_id, cluster as attributes."""
    err = AuthorizationError(
        customer_id="cust-1",
        reason="account not in consent scope",
        account_id="cust-1-savings",
        cluster="ACCOUNTS",
    )
    assert err.customer_id == "cust-1"
    assert err.reason == "account not in consent scope"
    assert err.account_id == "cust-1-savings"
    assert err.cluster == "ACCOUNTS"
    assert "cust-1" in str(err)


def test_authorization_error_minimal_attributes() -> None:
    """AuthorizationError works with only customer_id and reason."""
    err = AuthorizationError(customer_id="cust-2", reason="test")
    assert err.account_id is None
    assert err.cluster is None


# ---------------------------------------------------------------------------
# default_consent_path
# ---------------------------------------------------------------------------


def test_default_consent_path_format() -> None:
    """default_consent_path returns a Path resolving to fixtures/data/consents.json."""
    path = default_consent_path()
    assert path.name == "consents.json"
    assert path.parts[-2] == "data"
    assert path.parts[-3] == "fixtures"


@pytest.mark.skipif(
    not default_consent_path().exists(),
    reason="fixtures/data/consents.json not yet generated (run python -m fixtures.generator)",
)
def test_default_authorizer_resolves_committed_consents() -> None:
    """default_authorizer() wires to the committed consents.json and resolves all 3 tokens."""
    from banking_client.auth import default_authorizer

    auth = default_authorizer()
    # cust-001: single account, both clusters
    scope_001 = auth.authorize(_TOKEN_001, "cust-001-checking", DataCluster.ACCOUNTS)
    assert scope_001.customer_id == "cust-001"
    # cust-003: narrow — checking is allowed, retirement is not
    scope_003 = auth.authorize(_TOKEN_003, "cust-003-checking", DataCluster.ACCOUNTS)
    assert scope_003.customer_id == "cust-003"
    with pytest.raises(AuthorizationError):
        auth.authorize(_TOKEN_003, "cust-003-retirement", DataCluster.ACCOUNTS)


# ---------------------------------------------------------------------------
# Determinism: ConsentRegistry serializes identically on repeated calls
# ---------------------------------------------------------------------------


def test_registry_serialization_is_deterministic() -> None:
    """Repeated model_dump_json calls on the same registry produce identical output."""
    registry = ConsentRegistry(root=_DEFAULT_REGISTRY)
    first = registry.model_dump_json(by_alias=True, indent=2)
    second = registry.model_dump_json(by_alias=True, indent=2)
    assert first == second


def test_consent_scope_serialization_is_deterministic() -> None:
    """Repeated model_dump_json calls on the same scope produce identical output."""
    first = _SCOPE_003_NARROW.model_dump_json(by_alias=True, indent=2)
    second = _SCOPE_003_NARROW.model_dump_json(by_alias=True, indent=2)
    assert first == second


def test_scope_expiry_one_second_before_does_not_raise(tmp_path: Path) -> None:
    """A token expiring in 1 second is still valid (strictly less than expiry)."""
    expiry = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    active_scope = ConsentScope(
        consent_id="c-close",
        customer_id="cust-close",
        account_ids=frozenset(["acct-close"]),
        data_clusters=frozenset([DataCluster.ACCOUNTS]),
        expires_at=expiry,
    )
    path = _write_registry(tmp_path, {"tok_close": active_scope})
    now = expiry - timedelta(seconds=1)
    resolver = FixtureConsentResolver(path, now=lambda: now)
    scope = resolver.resolve("tok_close")
    assert scope.customer_id == "cust-close"
