"""Account data-source abstraction — the fixture ↔ HTTP swap seam.

:class:`AccountDataSource` is a structural :class:`~typing.Protocol` that defines the minimum
surface the :class:`~banking_client.client.accounts.AccountsClient` requires from any backing
store.  Today's implementation is :class:`FixtureAccountDataSource`, which reads the committed
JSON fixtures under ``fixtures/data/customers/``.  The Week-N HTTP implementation will satisfy
the same protocol — no caller changes required.

Swap seam design
----------------
Both ``token`` and ``customer_id`` are forwarded to every source method:

- ``customer_id`` is the **trusted** authoritative identifier returned by
  :meth:`~banking_client.auth.guard.Authorizer.authorize` /
  :meth:`~banking_client.auth.guard.Authorizer.authorize_scope`. The fixture implementation
  uses it to locate the right ``<customer_id>.json`` file.
- ``token`` is the raw bearer token. The fixture implementation ignores it; a future
  :class:`HttpAccountDataSource` will use it in the ``Authorization: Bearer …`` header when
  calling the real FDX API endpoints.

Passing both fields keeps the protocol honest for both implementations without forcing the
fixture to participate in HTTP concerns or forcing the HTTP client to re-resolve the customer.

Caching
-------
:class:`FixtureAccountDataSource` caches parsed :class:`~banking_client.models.customer.Customer`
objects in memory by ``customer_id``.  Fixture files are read at most once per source instance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from banking_client.models.account import Account
from banking_client.models.customer import Customer


def default_fixture_data_dir() -> Path:
    """Return the path to the committed ``fixtures/data/`` directory.

    Resolves relative to this file's location: ``src/banking_client/client/source.py`` is
    three directories below the repo root (``src/banking_client/client/``), so ``parents[3]``
    reaches the repo root — the same depth as
    :func:`~banking_client.auth.resolver.default_consent_path`.

    Returns:
        Absolute path to ``<repo_root>/fixtures/data``.
    """
    return Path(__file__).resolve().parents[3] / "fixtures" / "data"


class AccountDataSource(Protocol):
    """Structural protocol for fetching account data.

    Any class with compatible ``list_accounts`` and ``get_account`` methods satisfies this
    protocol, enabling dependency injection without inheritance. The fixture implementation
    is :class:`FixtureAccountDataSource`; a production HTTP implementation satisfies the same
    protocol without any callers changing.
    """

    async def list_accounts(self, *, token: str, customer_id: str) -> list[Account]:
        """Return all accounts accessible for *customer_id*.

        Args:
            token: Bearer token (used by HTTP implementations for the Authorization header;
                ignored by fixture implementations).
            customer_id: Trusted customer identifier from the resolved consent scope.

        Returns:
            All :class:`~banking_client.models.account.Account` objects for the customer.
            May be an empty list if the customer has no accounts in the data source.
        """
        ...  # pragma: no cover

    async def get_account(self, *, token: str, customer_id: str, account_id: str) -> Account | None:
        """Return a single account by id, or ``None`` if it does not exist.

        Args:
            token: Bearer token (used by HTTP implementations; ignored by fixture ones).
            customer_id: Trusted customer identifier from the resolved consent scope.
            account_id: FDX account id to look up.

        Returns:
            The :class:`~banking_client.models.account.Account` if found, ``None`` otherwise.
            Callers are responsible for converting ``None`` to the appropriate error.
        """
        ...  # pragma: no cover


class FixtureAccountDataSource:
    """Read account data from the committed ``fixtures/data/customers/`` JSON files.

    Each file at ``<data_dir>/customers/<customer_id>.json`` is a serialised
    :class:`~banking_client.models.customer.Customer` (camelCase, matching FDX wire format).
    Parsed objects are cached in memory so each file is read at most once per source instance.

    This implementation is suitable for development, tests, and the MCP dev server.  It is the
    "left-hand side" of the fixture ↔ HTTP swap seam; replace it with an
    :class:`HttpAccountDataSource` to call a real FDX API.

    Args:
        data_dir: Filesystem path to the ``fixtures/data`` directory.  Defaults to the result
            of :func:`default_fixture_data_dir`.

    Example::

        source = FixtureAccountDataSource(default_fixture_data_dir())
        accounts = await source.list_accounts(token="tok_cust_001", customer_id="cust-001")
    """

    def __init__(self, data_dir: Path) -> None:
        """Bind the data directory and initialise an empty in-memory cache.

        Args:
            data_dir: Path to the ``fixtures/data`` directory.
        """
        self._data_dir = data_dir
        self._cache: dict[str, Customer] = {}

    def _load_customer(self, customer_id: str) -> Customer | None:
        """Parse and cache the customer JSON file, returning ``None`` if absent.

        Args:
            customer_id: The customer whose file to load.

        Returns:
            The parsed :class:`~banking_client.models.customer.Customer`, or ``None`` if the
            file does not exist.
        """
        if customer_id in self._cache:
            return self._cache[customer_id]

        path = self._data_dir / "customers" / f"{customer_id}.json"
        if not path.is_file():
            return None

        customer = Customer.model_validate(json.loads(path.read_text(encoding="utf-8")))
        self._cache[customer_id] = customer
        return customer

    async def list_accounts(self, *, token: str, customer_id: str) -> list[Account]:
        """Return all accounts for *customer_id* from the fixture file.

        The ``token`` argument is accepted for protocol compatibility but is not used — fixture
        data is keyed by ``customer_id``, not by bearer token.

        Args:
            token: Bearer token (ignored in this implementation).
            customer_id: Trusted customer identifier; maps to ``customers/<id>.json``.

        Returns:
            The :class:`~banking_client.models.account.Account` list from the customer record,
            or an empty list if no fixture file exists for *customer_id*.
        """
        customer = self._load_customer(customer_id)
        return customer.accounts if customer is not None else []

    async def get_account(self, *, token: str, customer_id: str, account_id: str) -> Account | None:
        """Return a single account by id from the fixture file.

        The ``token`` argument is accepted for protocol compatibility but is not used.

        Args:
            token: Bearer token (ignored in this implementation).
            customer_id: Trusted customer identifier; maps to ``customers/<id>.json``.
            account_id: FDX account id to look up within the customer's account list.

        Returns:
            The matching :class:`~banking_client.models.account.Account`, or ``None`` if the
            customer file does not exist or the account id is not present in it.
        """
        customer = self._load_customer(customer_id)
        if customer is None:
            return None
        for account in customer.accounts:
            if account.id == account_id:
                return account
        return None
