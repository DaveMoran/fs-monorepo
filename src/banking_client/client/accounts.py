"""Async FDX account client — the Core Exchange endpoint layer.

:class:`AccountsClient` wraps a :class:`~banking_client.client.source.AccountDataSource` with
an :class:`~banking_client.auth.guard.Authorizer` and an
:class:`~common.audit.trail.AuditTrail` to deliver the three FDX Core Exchange account
endpoints.  Every public method is guaranteed to:

1. Go through the auth guard (no un-audited data access is possible).
2. Emit exactly one audit event per call (via ``@audited`` applied per-instance).
3. Return a typed Pydantic model (or raise a typed error — never a bare exception).

Per-instance ``@audited`` pattern
----------------------------------
The ``@audited`` decorator captures its :class:`~common.audit.trail.AuditTrail` at **decoration
time**, not call time.  Class-level decoration would therefore permanently bind the module-
default :class:`~common.audit.sinks.StdoutJSONSink` trail, making the trail un-injectable in
tests.  Instead, ``__init__`` applies the decorator to each private method and assigns the
result to a public attribute — so the trail passed at construction time is the one that
receives every event.

Pagination
----------
:meth:`~AccountsClient.get_accounts` implements FDX-style offset-cursor pagination.  The
``page_key`` parameter is an opaque URL-safe base64–encoded integer offset, not a raw page
number.  Callers must treat it as an opaque handle; the encoding details may change without
notice.  ``next_offset`` is ``None`` on the last page; ``prev_offset`` is ``None`` on the
first page.

One-event-per-call guarantee
-----------------------------
:meth:`~AccountsClient.get_balances` calls the private ``_require_account`` helper directly
(not the audited ``get_account`` public method) to ensure exactly one audit event is emitted
per call, not two.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from banking_client.auth.clusters import DataCluster
from banking_client.auth.guard import Authorizer, default_authorizer
from banking_client.auth.scope import ConsentScope
from banking_client.client.errors import AccountNotFoundError, InvalidPageCursorError  # noqa: F401 (re-exported)
from banking_client.client.pagination import (  # noqa: F401 (_decode_cursor/_encode_cursor re-exported for existing tests)
    _decode_cursor,
    _encode_cursor,
    paginate,
)
from banking_client.client.source import AccountDataSource, FixtureAccountDataSource, default_fixture_data_dir
from banking_client.models.account import Account, Balance
from banking_client.models.pagination import PaginatedResponse
from common.audit import AuditTrail, audited


def _paginate(items: list[Account], limit: int, page_key: str | None) -> PaginatedResponse[Account]:
    """Slice *items* at the requested cursor position and wrap in a paginated envelope.

    Thin wrapper around :func:`~banking_client.client.pagination.paginate` that fixes the
    ``for_request`` context string.  Kept here so existing imports of
    ``banking_client.client.accounts._paginate`` continue to work.

    Args:
        items: The full sorted list of accounts to paginate.
        limit: Maximum number of items to return in this page.
        page_key: Opaque cursor from a prior response; ``None`` means start from the beginning.

    Returns:
        A :class:`~banking_client.models.pagination.PaginatedResponse` containing the page
        window and metadata indicating whether further pages exist.

    Raises:
        InvalidPageCursorError: If *page_key* is provided but cannot be decoded.
    """
    return paginate(items, limit, page_key, for_request="get_accounts")


class AccountsClient:
    """Async FDX Core Exchange account client.

    Wraps a :class:`~banking_client.client.source.AccountDataSource` and routes every request
    through an :class:`~banking_client.auth.guard.Authorizer` and an
    :class:`~common.audit.trail.AuditTrail`.  All three public methods are fully typed and
    raise only the typed errors documented on :mod:`banking_client.client.errors` or the auth-
    layer errors from :mod:`common.errors`.

    Args:
        data_source: Any object satisfying
            :class:`~banking_client.client.source.AccountDataSource`.
        authorizer: The authorization guard; defaults to
            :func:`~banking_client.auth.guard.default_authorizer`.
        trail: Audit trail to record events to.  Defaults to a new
            :class:`~common.audit.trail.AuditTrail` backed by
            :class:`~common.audit.sinks.StdoutJSONSink`.  Inject an
            ``AuditTrail(sink=ListSink())`` in tests to capture and assert events.
        page_size: Default number of accounts per page when ``limit`` is not supplied.
            Defaults to 25.

    Public methods
    --------------
    ``get_accounts``, ``get_account``, and ``get_balances`` are **callables** (not plain
    methods) assigned in ``__init__`` so the injected *trail* is captured at decoration time.
    Their call signatures are documented in the private counterparts below.

    Example::

        client = default_accounts_client()
        page = await client.get_accounts("tok_cust_002", limit=2)
        account = await client.get_account("tok_cust_002", "cust-002-checking")
        balances = await client.get_balances("tok_cust_002", "cust-002-checking")
    """

    get_accounts: Callable[..., Awaitable[PaginatedResponse[Account]]]
    """Audited callable for :meth:`_get_accounts`; assigned in ``__init__``."""
    get_account: Callable[..., Awaitable[Account]]
    """Audited callable for :meth:`_get_account`; assigned in ``__init__``."""
    get_balances: Callable[..., Awaitable[list[Balance]]]
    """Audited callable for :meth:`_get_balances`; assigned in ``__init__``."""

    def __init__(
        self,
        data_source: AccountDataSource,
        authorizer: Authorizer,
        *,
        trail: AuditTrail | None = None,
        page_size: int = 25,
    ) -> None:
        """Wire the data source, authorizer, audit trail, and pagination defaults.

        Applies ``@audited`` to each private method per-instance so the supplied *trail* is
        captured at decoration time (the decorator binds the trail when the decorator factory
        is called, not when the resulting wrapper is invoked).

        Args:
            data_source: Backing store for account data.
            authorizer: Auth guard enforcing consent scope on every request.
            trail: Audit trail; defaults to :class:`~common.audit.trail.AuditTrail` with
                :class:`~common.audit.sinks.StdoutJSONSink`.
            page_size: Default page size for :meth:`_get_accounts`.
        """
        self._data_source = data_source
        self._authorizer = authorizer
        self._trail = trail if trail is not None else AuditTrail()
        self._page_size = page_size

        _cluster = DataCluster.ACCOUNTS
        self.get_accounts = audited("get_accounts", data_cluster=_cluster, trail=self._trail)(self._get_accounts)
        self.get_account = audited("get_account", data_cluster=_cluster, trail=self._trail)(self._get_account)
        self.get_balances = audited("get_balances", data_cluster=_cluster, trail=self._trail)(self._get_balances)

    # ------------------------------------------------------------------
    # Private implementations (decorated and exposed as public callables)
    # ------------------------------------------------------------------

    async def _get_accounts(
        self,
        token: str,
        *,
        limit: int | None = None,
        page_key: str | None = None,
    ) -> PaginatedResponse[Account]:
        """List the accounts the token is authorized to see.

        Resolves the token to a :class:`~banking_client.auth.scope.ConsentScope`, fetches all
        accounts for the resolved customer, filters to those in the consent scope, sorts by
        account id for stable ordering, and slices to the requested page.

        Args:
            token: Opaque bearer token.
            limit: Maximum accounts per page.  Defaults to ``page_size`` supplied at
                construction.
            page_key: Opaque cursor from a prior :meth:`_get_accounts` response; ``None``
                means start from the beginning.

        Returns:
            A :class:`~banking_client.models.pagination.PaginatedResponse` of
            :class:`~banking_client.models.account.Account`.

        Raises:
            AuthenticationError: Token unknown or expired.
            AuthorizationError: ACCOUNTS cluster not in consent scope.
            InvalidPageCursorError: *page_key* cannot be decoded.
        """
        scope: ConsentScope = self._authorizer.authorize_scope(token, DataCluster.ACCOUNTS)
        all_accounts = await self._data_source.list_accounts(token=token, customer_id=scope.customer_id)
        visible = sorted(
            (a for a in all_accounts if a.id in scope.account_ids),
            key=lambda a: a.id,
        )
        return _paginate(visible, limit if limit is not None else self._page_size, page_key)

    async def _get_account(self, token: str, account_id: str) -> Account:
        """Return a single account by id.

        Args:
            token: Opaque bearer token.
            account_id: FDX account id to retrieve.

        Returns:
            The :class:`~banking_client.models.account.Account` with *account_id*.

        Raises:
            AuthenticationError: Token unknown or expired.
            AuthorizationError: Account or ACCOUNTS cluster outside consent scope.
            AccountNotFoundError: Account is in scope but absent from the data source.
        """
        scope: ConsentScope = self._authorizer.authorize(token, account_id, DataCluster.ACCOUNTS)
        return await self._require_account(token, scope, account_id)

    async def _get_balances(self, token: str, account_id: str) -> list[Balance]:
        """Return the balances for a single account.

        Calls :meth:`_require_account` directly (not the audited ``get_account``) so that
        exactly one audit event is emitted per ``get_balances`` call.

        Args:
            token: Opaque bearer token.
            account_id: FDX account id whose balances to retrieve.

        Returns:
            The :class:`~banking_client.models.account.Balance` list embedded in the account.
            Empty list if the account has no reported balances.

        Raises:
            AuthenticationError: Token unknown or expired.
            AuthorizationError: Account or ACCOUNTS cluster outside consent scope.
            AccountNotFoundError: Account is in scope but absent from the data source.
        """
        scope: ConsentScope = self._authorizer.authorize(token, account_id, DataCluster.ACCOUNTS)
        account = await self._require_account(token, scope, account_id)
        return account.balances

    async def _require_account(self, token: str, scope: ConsentScope, account_id: str) -> Account:
        """Fetch an account and raise :exc:`AccountNotFoundError` if absent.

        Shared by :meth:`_get_account` and :meth:`_get_balances` to avoid code duplication
        and ensure that neither calls the other's audited public wrapper.

        Args:
            token: Bearer token forwarded to the data source.
            scope: Resolved consent scope containing the trusted ``customer_id``.
            account_id: FDX account id to fetch.

        Returns:
            The :class:`~banking_client.models.account.Account`.

        Raises:
            AccountNotFoundError: The data source returned ``None`` for *account_id*.
        """
        account: Account | None = await self._data_source.get_account(
            token=token,
            customer_id=scope.customer_id,
            account_id=account_id,
        )
        if account is None:
            raise AccountNotFoundError(account_id)
        return account


def default_accounts_client(*, trail: AuditTrail | None = None) -> AccountsClient:
    """Return an :class:`AccountsClient` wired to the committed fixture data.

    Uses :class:`~banking_client.client.source.FixtureAccountDataSource` over
    :func:`~banking_client.client.source.default_fixture_data_dir` and
    :func:`~banking_client.auth.guard.default_authorizer` over the committed
    ``fixtures/data/consents.json``.

    This is the development / MCP dev server factory.  The data-source and authorizer can be
    swapped independently: pass custom instances to :class:`AccountsClient` directly for fine-
    grained control, or replace :func:`~banking_client.auth.guard.default_authorizer` alone
    to switch to a real OAuth resolver while keeping the fixture data source.

    Args:
        trail: Optional audit trail override.  Defaults to ``None`` (an
            :class:`~common.audit.trail.AuditTrail` backed by
            :class:`~common.audit.sinks.StdoutJSONSink` is created inside
            :class:`AccountsClient`).  Pass ``AuditTrail(sink=ListSink())`` in tests to
            avoid creating a process-global :class:`~common.audit.sinks.StdoutJSONSink`
            that can interfere with :mod:`capsys` capture in the test suite.

    Returns:
        A fully wired :class:`AccountsClient` ready for async use.

    Example::

        client = default_accounts_client()
        page = await client.get_accounts("tok_cust_002")
    """
    return AccountsClient(
        data_source=FixtureAccountDataSource(default_fixture_data_dir()),
        authorizer=default_authorizer(),
        trail=trail,
    )


# Type alias re-exported for convenience.
_AnyReturn = Any
