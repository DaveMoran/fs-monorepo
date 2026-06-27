"""Async FDX transaction client — the Core Exchange endpoint layer.

:class:`TransactionsClient` wraps a
:class:`~banking_client.client.transaction_source.TransactionDataSource` with an
:class:`~banking_client.auth.guard.Authorizer` and an
:class:`~common.audit.trail.AuditTrail` to deliver the FDX Core Exchange transactions
endpoint.  Every public method is guaranteed to:

1. Go through the auth guard (no un-audited data access is possible).
2. Emit exactly one audit event per call (via ``@audited`` applied per-instance).
3. Return a typed Pydantic model (or raise a typed error — never a bare exception).

Per-instance ``@audited`` pattern
----------------------------------
The ``@audited`` decorator captures its :class:`~common.audit.trail.AuditTrail` at **decoration
time**, not call time.  ``__init__`` applies the decorator to the private method and assigns the
result to the public attribute ``get_transactions`` — so the trail passed at construction time
is the one that receives every event.

Date filtering
--------------
:meth:`~TransactionsClient.get_transactions` accepts ``start_time`` and ``end_time`` bounds
(both inclusive) that filter on ``postedTimestamp`` per the FDX convention.  A ``None``
``postedTimestamp`` (PENDING transaction) cannot fall inside a posted-date window, so pending
transactions are **excluded whenever any date bound is set**.  With no date bounds, pending
transactions are included (subject to the ``status`` filter).

Status filtering
----------------
The optional ``status`` parameter accepts a
:class:`~banking_client.models.enums.TransactionStatus` value.  ``None`` (the default) returns
all transactions; ``POSTED`` or ``PENDING`` restricts results to that status.

Pagination
----------
:meth:`~TransactionsClient.get_transactions` implements FDX-style offset-cursor pagination via
:func:`~banking_client.client.pagination.paginate`.  The ``page_key`` is an opaque URL-safe
base64-encoded integer offset into the **filtered** result list.  ``page.total`` reflects the
post-filter count, and ``next_offset`` is ``None`` on the last page.  Callers must keep the
same filter arguments across pages; changing a filter with a stale cursor returns an
undefined window.

One-event-per-call guarantee
------------------------------
``get_transactions`` is the sole public method.  It is the per-instance ``@audited``-wrapped
function, so every call emits exactly one audit event — including on error (the audit trail
records ``outcome=ERROR`` and ``error_type`` before re-raising the exception).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from banking_client.auth.clusters import DataCluster
from banking_client.auth.guard import Authorizer, default_authorizer
from banking_client.auth.scope import ConsentScope
from banking_client.client.errors import InvalidDateRangeError, InvalidPageCursorError  # noqa: F401 (re-exported)
from banking_client.client.pagination import paginate
from banking_client.client.transaction_source import (
    FixtureTransactionDataSource,
    TransactionDataSource,
    default_fixture_data_dir,
)
from banking_client.models.enums import TransactionStatus
from banking_client.models.pagination import PaginatedResponse
from banking_client.models.transaction import Transaction
from common.audit import AuditTrail, audited


def _in_date_window(
    tx: Transaction,
    start_time: datetime | None,
    end_time: datetime | None,
) -> bool:
    """Return ``True`` when *tx* should be included given the requested date window.

    Filtering is on ``postedTimestamp`` per the FDX convention.  A transaction with a ``None``
    ``postedTimestamp`` (i.e. PENDING) has not settled and therefore cannot fall within a
    posted-date window — it is excluded whenever either bound is set.  When neither bound is
    set, all transactions pass (pending included), leaving the caller's ``status`` filter to
    further restrict if needed.

    Args:
        tx: The transaction to evaluate.
        start_time: Inclusive lower bound on ``postedTimestamp``; ``None`` means unbounded.
        end_time: Inclusive upper bound on ``postedTimestamp``; ``None`` means unbounded.

    Returns:
        ``True`` if the transaction falls within (or straddles) the requested window.
    """
    if start_time is None and end_time is None:
        return True

    posted = tx.posted_timestamp
    if posted is None:
        # PENDING — no settled date to compare; exclude when any bound is active.
        return False

    if start_time is not None and posted < start_time:
        return False
    return not (end_time is not None and posted > end_time)


class TransactionsClient:
    """Async FDX Core Exchange transaction client.

    Wraps a :class:`~banking_client.client.transaction_source.TransactionDataSource` and routes
    every request through an :class:`~banking_client.auth.guard.Authorizer` and an
    :class:`~common.audit.trail.AuditTrail`.  The single public method ``get_transactions`` is
    fully typed and raises only the typed errors documented on
    :mod:`banking_client.client.errors` or the auth-layer errors from :mod:`common.errors`.

    Args:
        data_source: Any object satisfying
            :class:`~banking_client.client.transaction_source.TransactionDataSource`.
        authorizer: The authorization guard; use
            :func:`~banking_client.auth.guard.default_authorizer` for the committed fixtures.
        trail: Audit trail to record events to.  Defaults to a new
            :class:`~common.audit.trail.AuditTrail` backed by
            :class:`~common.audit.sinks.StdoutJSONSink`.  Inject an
            ``AuditTrail(sink=ListSink())`` in tests to capture and assert events.
        page_size: Default number of transactions per page when ``limit`` is not supplied.
            Defaults to 25.

    Public methods
    --------------
    ``get_transactions`` is a **callable** (not a plain method) assigned in ``__init__`` so the
    injected *trail* is captured at decoration time.  Its call signature is documented in
    :meth:`_get_transactions`.

    Example::

        client = default_transactions_client()
        page = await client.get_transactions(
            "tok_cust_003",
            "cust-003-checking",
            start_time=datetime(2025, 1, 1, tzinfo=UTC),
            end_time=datetime(2025, 3, 31, 23, 59, 59, tzinfo=UTC),
            limit=50,
        )
    """

    get_transactions: Callable[..., Awaitable[PaginatedResponse[Transaction]]]
    """Audited callable for :meth:`_get_transactions`; assigned in ``__init__``."""

    def __init__(
        self,
        data_source: TransactionDataSource,
        authorizer: Authorizer,
        *,
        trail: AuditTrail | None = None,
        page_size: int = 25,
    ) -> None:
        """Wire the data source, authorizer, audit trail, and pagination defaults.

        Applies ``@audited`` to the private method per-instance so the supplied *trail* is
        captured at decoration time (the decorator binds the trail when the decorator factory
        is called, not when the resulting wrapper is invoked).

        Args:
            data_source: Backing store for transaction data.
            authorizer: Auth guard enforcing consent scope on every request.
            trail: Audit trail; defaults to :class:`~common.audit.trail.AuditTrail` with
                :class:`~common.audit.sinks.StdoutJSONSink`.
            page_size: Default page size for :meth:`_get_transactions`.
        """
        self._data_source = data_source
        self._authorizer = authorizer
        self._trail = trail if trail is not None else AuditTrail()
        self._page_size = page_size

        _cluster = DataCluster.TRANSACTIONS
        self.get_transactions = audited("get_transactions", data_cluster=_cluster, trail=self._trail)(
            self._get_transactions
        )

    # ------------------------------------------------------------------
    # Private implementation (decorated and exposed as a public callable)
    # ------------------------------------------------------------------

    async def _get_transactions(
        self,
        token: str,
        account_id: str,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        status: TransactionStatus | None = None,
        limit: int | None = None,
        page_key: str | None = None,
    ) -> PaginatedResponse[Transaction]:
        """Return a page of transactions for *account_id*, optionally filtered.

        Flow: **validate → auth guard → fetch → filter → sort → paginate**.

        The date range is validated before any data access so that an invalid range is
        rejected immediately.  The auth guard runs next, before any fixture or network I/O.
        Filtering and sorting are applied in-memory on the full unfiltered list from the
        data source; pagination then slices the sorted, filtered result.

        Args:
            token: Opaque bearer token.
            account_id: FDX account id whose transactions to retrieve.
            start_time: Inclusive lower bound on ``postedTimestamp``; ``None`` means unbounded.
                PENDING transactions are excluded whenever this or *end_time* is set.
            end_time: Inclusive upper bound on ``postedTimestamp``; ``None`` means unbounded.
            status: When given, restrict results to transactions with this
                :class:`~banking_client.models.enums.TransactionStatus`.  ``None`` returns all
                statuses.
            limit: Maximum transactions per page.  Defaults to ``page_size`` supplied at
                construction.
            page_key: Opaque cursor from a prior :meth:`_get_transactions` response for the
                **same filter arguments**; ``None`` means start from the beginning.

        Returns:
            A :class:`~banking_client.models.pagination.PaginatedResponse` of
            :class:`~banking_client.models.transaction.Transaction`.  ``page.total`` is the
            post-filter count; ``page.next_offset`` is ``None`` on the last page.

        Raises:
            InvalidDateRangeError: Both bounds are given and *start_time* > *end_time*.
            AuthenticationError: Token unknown or expired.
            AuthorizationError: TRANSACTIONS cluster or *account_id* not in consent scope.
            InvalidPageCursorError: *page_key* cannot be decoded.
        """
        # 1. Validate the date range before any I/O.
        if start_time is not None and end_time is not None and start_time > end_time:
            raise InvalidDateRangeError(start_time, end_time)

        # 2. Auth guard — single-account guard because transactions are per-account.
        scope: ConsentScope = self._authorizer.authorize(token, account_id, DataCluster.TRANSACTIONS)

        # 3. Fetch the full unfiltered list from the data source.
        all_txns = await self._data_source.list_transactions(
            token=token,
            customer_id=scope.customer_id,
            account_id=account_id,
        )

        # 4. Filter: date window, then status.
        filtered = [
            tx
            for tx in all_txns
            if _in_date_window(tx, start_time, end_time) and (status is None or tx.status == status)
        ]

        # 5. Sort deterministically by (transaction_timestamp, id) ascending.
        #    transaction_timestamp is always present (even for PENDING); using it avoids any
        #    None-comparison issue with posted_timestamp.
        filtered.sort(key=lambda tx: (tx.transaction_timestamp, tx.id))

        # 6. Paginate the filtered result.
        return paginate(
            filtered,
            limit if limit is not None else self._page_size,
            page_key,
            for_request="get_transactions",
        )


def default_transactions_client(*, trail: AuditTrail | None = None) -> TransactionsClient:
    """Return a :class:`TransactionsClient` wired to the committed fixture data.

    Uses :class:`~banking_client.client.transaction_source.FixtureTransactionDataSource` over
    :func:`~banking_client.client.source.default_fixture_data_dir` and
    :func:`~banking_client.auth.guard.default_authorizer` over the committed
    ``fixtures/data/consents.json``.

    This is the development / MCP dev server factory.  The data-source and authorizer can be
    swapped independently: pass custom instances to :class:`TransactionsClient` directly for
    fine-grained control.

    Args:
        trail: Optional audit trail override.  Defaults to ``None`` (an
            :class:`~common.audit.trail.AuditTrail` backed by
            :class:`~common.audit.sinks.StdoutJSONSink` is created inside
            :class:`TransactionsClient`).  Pass ``AuditTrail(sink=ListSink())`` in tests to
            avoid stdout noise.

    Returns:
        A fully wired :class:`TransactionsClient` ready for async use.

    Example::

        client = default_transactions_client()
        page = await client.get_transactions("tok_cust_003", "cust-003-checking", limit=50)
    """
    return TransactionsClient(
        data_source=FixtureTransactionDataSource(default_fixture_data_dir()),
        authorizer=default_authorizer(),
        trail=trail,
    )
