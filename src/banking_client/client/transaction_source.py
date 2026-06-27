"""Transaction data-source abstraction — the fixture ↔ HTTP swap seam.

:class:`TransactionDataSource` is a structural :class:`~typing.Protocol` that defines the
minimum surface :class:`~banking_client.client.transactions.TransactionsClient` requires from
any backing store.  Today's implementation is :class:`FixtureTransactionDataSource`, which
reads the committed JSON fixtures under ``fixtures/data/transactions/``.  A future HTTP
implementation will satisfy the same protocol — no caller changes required.

Swap seam design
----------------
Both ``token`` and ``customer_id`` are forwarded to every source method:

- ``customer_id`` is the **trusted** authoritative identifier returned by
  :meth:`~banking_client.auth.guard.Authorizer.authorize`.  The fixture implementation uses it
  only to validate the call path; fixture files are keyed by ``account_id`` directly.
- ``token`` is the raw bearer token.  The fixture implementation ignores it; a future
  :class:`HttpTransactionDataSource` will use it in the ``Authorization: Bearer …`` header.

No filtering in the source
--------------------------
All date-range, status, and pagination filtering is applied in
:class:`~banking_client.client.transactions.TransactionsClient`, not here.  This mirrors the
account-source contract (filtering happens in the client layer) and keeps the data source
responsible only for I/O — making it straightforward to push filters to an HTTP query string
in a future implementation without changing the protocol.

Fixture file format
-------------------
Each file at ``<data_dir>/transactions/<account_id>.json`` is a serialised
``PaginatedResponse[Transaction]`` (camelCase, FDX wire format).  The ``items`` array is
ordered by ``transactionTimestamp`` ascending with stable ``…-txn-NNNNN`` ids, as produced by
the synthetic data generator.  Only ``items`` is used here; the ``page`` envelope in the
fixture is discarded (the client builds its own envelope after filtering).

Caching
-------
:class:`FixtureTransactionDataSource` caches parsed transaction lists in memory by
``account_id``.  Fixture files are read at most once per source instance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from banking_client.client.source import default_fixture_data_dir  # re-used, not redefined
from banking_client.models.pagination import PaginatedResponse
from banking_client.models.transaction import Transaction


class TransactionDataSource(Protocol):
    """Structural protocol for fetching transaction data.

    Any class with a compatible ``list_transactions`` method satisfies this protocol, enabling
    dependency injection without inheritance.  The fixture implementation is
    :class:`FixtureTransactionDataSource`; a production HTTP implementation satisfies the same
    protocol without any callers changing.
    """

    async def list_transactions(
        self,
        *,
        token: str,
        customer_id: str,
        account_id: str,
    ) -> list[Transaction]:
        """Return all transactions for *account_id* within *customer_id*'s data.

        Implementations must return the **full unfiltered list** in ascending
        ``transaction_timestamp`` order.  All filtering (date range, status, pagination) is
        applied by the caller.

        Args:
            token: Bearer token (used by HTTP implementations for the Authorization header;
                ignored by fixture implementations).
            customer_id: Trusted customer identifier from the resolved consent scope.
            account_id: The FDX account id whose transactions to retrieve.

        Returns:
            All :class:`~banking_client.models.transaction.Transaction` objects for the
            account.  May be an empty list if the account has no transactions.
        """
        ...  # pragma: no cover


class FixtureTransactionDataSource:
    """Read transaction data from the committed ``fixtures/data/transactions/`` JSON files.

    Each file at ``<data_dir>/transactions/<account_id>.json`` is a serialised
    :class:`~banking_client.models.pagination.PaginatedResponse` of
    :class:`~banking_client.models.transaction.Transaction` (camelCase, FDX wire format).
    Only the ``items`` list is extracted; the fixture envelope's ``page`` metadata is discarded
    because the client rebuilds it after applying date-range and status filters.

    Parsed lists are cached in memory so each file is read at most once per source instance.

    This implementation is suitable for development, tests, and the MCP dev server.  Replace
    it with an :class:`HttpTransactionDataSource` to call a real FDX API endpoint.

    Args:
        data_dir: Filesystem path to the ``fixtures/data`` directory.  Defaults to the result
            of :func:`~banking_client.client.source.default_fixture_data_dir`.

    Example::

        source = FixtureTransactionDataSource(default_fixture_data_dir())
        txns = await source.list_transactions(
            token="tok_cust_003", customer_id="cust-003", account_id="cust-003-checking"
        )
    """

    def __init__(self, data_dir: Path) -> None:
        """Bind the data directory and initialise an empty in-memory cache.

        Args:
            data_dir: Path to the ``fixtures/data`` directory.
        """
        self._data_dir = data_dir
        self._cache: dict[str, list[Transaction]] = {}

    def _load_transactions(self, account_id: str) -> list[Transaction]:
        """Parse and cache the transaction JSON file, returning an empty list if absent.

        Reads ``<data_dir>/transactions/<account_id>.json``, deserialises it as a
        ``PaginatedResponse[Transaction]``, and caches the ``items`` list.  Absent files
        return an empty list (not an error — some accounts may simply have no history yet).

        Args:
            account_id: The account whose transaction file to load.

        Returns:
            The list of :class:`~banking_client.models.transaction.Transaction` objects,
            or ``[]`` if no fixture file exists for *account_id*.
        """
        if account_id in self._cache:
            return self._cache[account_id]

        path = self._data_dir / "transactions" / f"{account_id}.json"
        if not path.is_file():
            self._cache[account_id] = []
            return []

        raw = PaginatedResponse[Transaction].model_validate(json.loads(path.read_text(encoding="utf-8")))
        self._cache[account_id] = raw.items
        return raw.items

    async def list_transactions(
        self,
        *,
        token: str,
        customer_id: str,
        account_id: str,
    ) -> list[Transaction]:
        """Return all transactions for *account_id* from the fixture file.

        The ``token`` and ``customer_id`` arguments are accepted for protocol compatibility
        but are not used — fixture data is keyed by ``account_id`` directly.

        Args:
            token: Bearer token (ignored in this implementation).
            customer_id: Trusted customer identifier (ignored in this implementation).
            account_id: FDX account id; maps to ``transactions/<account_id>.json``.

        Returns:
            The :class:`~banking_client.models.transaction.Transaction` list from the fixture,
            or an empty list if no fixture file exists for *account_id*.
        """
        return self._load_transactions(account_id)


__all__: list[str] = [
    "FixtureTransactionDataSource",
    "TransactionDataSource",
    "default_fixture_data_dir",
]
