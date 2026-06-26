"""FDX Core Exchange account client.

Public surface of the ``banking_client.client`` subpackage.  Import from here rather than
from the internal modules so internal organisation can change without breaking callers.

Data-source seam
----------------
:class:`AccountDataSource` and :class:`FixtureAccountDataSource` are the fixture ↔ HTTP swap
seam.  The fixture implementation reads the committed JSON files; a future
``HttpAccountDataSource`` will satisfy the same :class:`~typing.Protocol` and call the real FDX
REST endpoints.  Only :func:`default_accounts_client` changes when the production data source is
plugged in — all callers and tests are unaffected.

Error hierarchy
---------------
Client-layer errors complement the auth-layer errors from :mod:`common.errors`:

- :class:`AccountNotFoundError` — authorized account id absent from the data source (HTTP 404).
- :class:`InvalidPageCursorError` — malformed ``page_key`` cursor (HTTP 400).
- :class:`~common.errors.AuthenticationError` — unknown or expired token (HTTP 401).
- :class:`~common.errors.AuthorizationError` — token valid but request outside scope (HTTP 403).
"""

from __future__ import annotations

from banking_client.client.accounts import AccountsClient, default_accounts_client
from banking_client.client.errors import AccountNotFoundError, InvalidPageCursorError
from banking_client.client.source import AccountDataSource, FixtureAccountDataSource, default_fixture_data_dir

__all__: list[str] = [
    "AccountDataSource",
    "AccountNotFoundError",
    "AccountsClient",
    "FixtureAccountDataSource",
    "InvalidPageCursorError",
    "default_accounts_client",
    "default_fixture_data_dir",
]
