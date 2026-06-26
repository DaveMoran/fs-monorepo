"""Authorization and consent boundary for the FDX banking client.

This subpackage enforces the FDX principle that a third party may access *only* the data a
customer has explicitly permissioned — never another customer's data, and only the specific
accounts and data clusters covered by the consent grant.

Public surface
--------------
- :class:`DataCluster` — the categories of financial data a consent grant can permission.
- :class:`ConsentScope` — the resolved grant: one customer, a set of account ids, a set of
  data clusters, and an optional expiry.
- :class:`ConsentRegistry` — the ``{token: scope}`` document model for ``consents.json``.
- :class:`ConsentResolver` — :class:`~typing.Protocol` defining the token→scope resolution
  contract. The stub implementation is :class:`FixtureConsentResolver`; the Week 20 OAuth
  implementation will satisfy the same protocol without changing any caller.
- :class:`FixtureConsentResolver` — loads and resolves tokens from the committed
  ``fixtures/data/consents.json``.
- :class:`Authorizer` — the guard every data-access wrapper calls. Given a token, an account
  id, and a data cluster, it either returns the trusted :class:`ConsentScope` or raises
  :class:`~common.errors.AuthenticationError` / :class:`~common.errors.AuthorizationError`.
- :func:`default_consent_path` — resolves the path to the committed ``consents.json``.
- :func:`default_authorizer` — factory wiring the stub resolver; one-line swap point for Week 20.
"""

from __future__ import annotations

from banking_client.auth.clusters import DataCluster
from banking_client.auth.guard import Authorizer, default_authorizer
from banking_client.auth.resolver import ConsentResolver, FixtureConsentResolver, default_consent_path
from banking_client.auth.scope import ConsentRegistry, ConsentScope

__all__: list[str] = [
    "Authorizer",
    "ConsentRegistry",
    "ConsentResolver",
    "ConsentScope",
    "DataCluster",
    "FixtureConsentResolver",
    "default_authorizer",
    "default_consent_path",
]
