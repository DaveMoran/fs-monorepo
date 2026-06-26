"""Authorization guard — the entry point for every data-access request.

:class:`Authorizer` is the single gate every banking-client wrapper calls before reading any
FDX data. It combines token resolution (via :class:`~banking_client.auth.resolver.ConsentResolver`)
with consent enforcement (account-id membership and data-cluster membership checks).

Design rationale
----------------
The guard returns the resolved :class:`~banking_client.auth.scope.ConsentScope` on success so
callers receive the *trusted* ``customer_id`` to use when fetching data — they do not derive
it from the raw token or from parsing the account id. This is defense-in-depth: even if an
account id's embedded customer prefix were somehow wrong, the scope's ``customer_id`` is the
authoritative value.

Cross-customer isolation is structural, not heuristic: ``cust-001``'s scope lists only
``cust-001-*`` account ids, so requesting ``cust-002-checking`` fails the membership test even
without inspecting the id format.

Failure modes
-------------
- :class:`~common.errors.AuthenticationError` — unknown or expired token (raised by the
  resolver before any scope check runs).
- :class:`~common.errors.AuthorizationError` — valid token but the requested
  ``(account_id, data_cluster)`` combination is outside the consent scope.
"""

from __future__ import annotations

from banking_client.auth.clusters import DataCluster
from banking_client.auth.resolver import ConsentResolver, FixtureConsentResolver, default_consent_path
from banking_client.auth.scope import ConsentScope
from common.errors import AuthorizationError


class Authorizer:
    """Authorization guard; enforces consent scope on every data-access request.

    Args:
        resolver: Any object satisfying :class:`~banking_client.auth.resolver.ConsentResolver`
            — today :class:`~banking_client.auth.resolver.FixtureConsentResolver`, in Week 20
            an OAuth-backed resolver.

    Example::

        auth = default_authorizer()
        scope = auth.authorize("tok_cust_001", "cust-001-checking", DataCluster.ACCOUNTS)
        # scope.customer_id == "cust-001"
    """

    def __init__(self, resolver: ConsentResolver) -> None:
        """Bind the resolver this guard delegates token lookup to."""
        self._resolver = resolver

    def authorize(self, token: str, account_id: str, cluster: DataCluster) -> ConsentScope:
        """Verify the request is within consent scope and return the trusted scope.

        Raises :class:`~common.errors.AuthenticationError` before any scope check if the
        token is unknown or expired (delegated to the resolver). Then checks account-id
        membership and data-cluster membership; either failure raises
        :class:`~common.errors.AuthorizationError`.

        Args:
            token: Opaque bearer token from the caller.
            account_id: The FDX account id being requested (e.g. ``"cust-001-checking"``).
            cluster: The :class:`DataCluster` the caller wants to read.

        Returns:
            The :class:`~banking_client.auth.scope.ConsentScope` for *token*. Callers should
            use ``scope.customer_id`` — not the token or the account id prefix — as the
            authoritative customer identifier for data fetching.

        Raises:
            AuthenticationError: Token unknown or expired.
            AuthorizationError: Account or cluster not in consent scope.
        """
        scope: ConsentScope = self._resolver.resolve(token)

        if account_id not in scope.account_ids:
            raise AuthorizationError(
                customer_id=scope.customer_id,
                reason="account not in consent scope",
                account_id=account_id,
            )

        if cluster not in scope.data_clusters:
            raise AuthorizationError(
                customer_id=scope.customer_id,
                reason="data cluster not in consent scope",
                account_id=account_id,
                cluster=str(cluster),
            )

        return scope


def default_authorizer() -> Authorizer:
    """Return an :class:`Authorizer` backed by the committed ``consents.json`` fixture.

    This is the **one-line Week 20 swap point**: replace the body with an
    ``OAuthConsentResolver`` constructor and nothing else in the codebase changes::

        # Week 20: swap this one line
        return Authorizer(OAuthConsentResolver(jwks_uri=settings.JWKS_URI))

    Returns:
        An :class:`Authorizer` using :class:`~banking_client.auth.resolver.FixtureConsentResolver`
        and :func:`~banking_client.auth.resolver.default_consent_path`.
    """
    return Authorizer(FixtureConsentResolver(default_consent_path()))
