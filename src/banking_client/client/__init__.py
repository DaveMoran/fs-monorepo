"""FDX Core Exchange account and transaction clients.

Public surface of the ``banking_client.client`` subpackage.  Import from here rather than
from the internal modules so internal organisation can change without breaking callers.

Data-source seams
-----------------
:class:`AccountDataSource` / :class:`FixtureAccountDataSource` and
:class:`TransactionDataSource` / :class:`FixtureTransactionDataSource` are the fixture ↔ HTTP
swap seams.  The fixture implementations read the committed JSON files; future HTTP
implementations will satisfy the same :class:`~typing.Protocol` contracts and call the real FDX
REST endpoints.  Only the factory functions change when a production data source is plugged in.

Error hierarchy
---------------
Client-layer errors complement the auth-layer errors from :mod:`common.errors`:

- :class:`AccountNotFoundError` — authorized account id absent from the data source (HTTP 404).
- :class:`InvalidPageCursorError` — malformed ``page_key`` cursor (HTTP 400).
- :class:`InvalidDateRangeError` — ``start_time`` later than ``end_time`` (HTTP 400).
- :class:`~common.errors.AuthenticationError` — unknown or expired token (HTTP 401).
- :class:`~common.errors.AuthorizationError` — token valid but request outside scope (HTTP 403).
"""

from __future__ import annotations

from banking_client.client.accounts import AccountsClient, default_accounts_client
from banking_client.client.errors import AccountNotFoundError, InvalidDateRangeError, InvalidPageCursorError
from banking_client.client.source import AccountDataSource, FixtureAccountDataSource, default_fixture_data_dir
from banking_client.client.transaction_source import FixtureTransactionDataSource, TransactionDataSource
from banking_client.client.transactions import TransactionsClient, default_transactions_client

__all__: list[str] = [
    "AccountDataSource",
    "AccountNotFoundError",
    "AccountsClient",
    "FixtureAccountDataSource",
    "FixtureTransactionDataSource",
    "InvalidDateRangeError",
    "InvalidPageCursorError",
    "TransactionDataSource",
    "TransactionsClient",
    "default_accounts_client",
    "default_fixture_data_dir",
    "default_transactions_client",
]
