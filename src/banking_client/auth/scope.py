"""Consent scope model and on-disk registry format.

A :class:`ConsentScope` is the resolved representation of what a bearer token is authorised to
access: exactly one customer, a specific set of account ids, and a specific set of data
clusters. It is the single source of truth that the :class:`~banking_client.auth.guard.Authorizer`
evaluates on every request.

Design notes
------------
Frozen model
    Unlike the mutable FDX wire models (see :class:`~banking_client.models.base.FDXBaseModel`),
    :class:`ConsentScope` is ``frozen=True``. A security primitive must be immutable — once
    resolved from a token it cannot be accidentally mutated by caller code.

``frozenset`` fields
    :attr:`~ConsentScope.account_ids` and :attr:`~ConsentScope.data_clusters` are
    ``frozenset`` for correct in-memory membership semantics (``in`` is O(1), unhashable
    elements are rejected at parse time). Serialization uses :func:`~ConsentScope._serialize_account_ids`
    and :func:`~ConsentScope._serialize_data_clusters` to emit *sorted* lists, keeping the
    committed ``consents.json`` byte-stable across re-generation runs.

Wire format (camelCase)
    The model uses :func:`~pydantic.alias_generators.to_camel` so the on-disk JSON is FDX-
    faithful (``consentId``, ``customerId``, ``accountIds``, …) while Python code uses
    ``snake_case``.

:class:`ConsentRegistry` is the top-level document model for ``consents.json``:
``{ "<bearer-token>": { <ConsentScope, camelCase> }, ... }``. The token is the dict key and
never appears inside the scope — bearer tokens are opaque handles; the scope is the payload
they unlock.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, RootModel, field_serializer
from pydantic.alias_generators import to_camel

from banking_client.auth.clusters import DataCluster


class ConsentScope(BaseModel):
    """The data access grant associated with a bearer token.

    Attributes:
        consent_id: Stable opaque handle for this grant (maps to FDX ``consentId``). Intended
            to survive token rotation — in a full OAuth flow the consent grant lives longer than
            any individual access token.
        customer_id: The single customer this scope speaks for (e.g. ``"cust-001"``). Every
            data-access call resolves through the authorised scope, so cross-customer access
            is structurally impossible — a token for cust-001 simply cannot produce a scope
            whose ``customer_id`` is ``"cust-002"``.
        account_ids: The exact set of account ids the token is authorised to read. The
            authorisation guard performs set-membership checks, not prefix matching, so access
            to an account requires an explicit grant.
        data_clusters: The data clusters permissioned by this grant. Both account-level and
            cluster-level checks must pass before a request proceeds.
        expires_at: Consent expiry in UTC. ``None`` means no expiry, which is the stub
            behaviour. The :class:`~banking_client.auth.resolver.FixtureConsentResolver`
            honours this field so expiry tests work without a real OAuth server.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
    )

    consent_id: str
    """FDX consentId — stable, opaque, survives token rotation."""
    customer_id: str
    """The one customer this scope speaks for (e.g. ``"cust-001"``)."""
    account_ids: frozenset[str]
    """The set of account ids the token is authorised to read."""
    data_clusters: frozenset[DataCluster]
    """The data clusters permissioned by this grant."""
    expires_at: datetime | None = None
    """Consent expiry in UTC; ``None`` means no expiry (stub behaviour)."""

    @field_serializer("account_ids")
    def _serialize_account_ids(self, v: frozenset[str]) -> list[str]:
        """Emit account ids as a sorted list for byte-stable JSON output."""
        return sorted(v)

    @field_serializer("data_clusters")
    def _serialize_data_clusters(self, v: frozenset[DataCluster]) -> list[str]:
        """Emit data clusters as a sorted list for byte-stable JSON output."""
        return sorted(v)


class ConsentRegistry(RootModel[dict[str, ConsentScope]]):
    """On-disk format for ``consents.json``: bearer token → :class:`ConsentScope`.

    The token string is the dict key; the scope is the payload. Tokens never appear inside
    the scope itself — they are opaque references, not self-describing credentials.

    Example::

        {
          "tok_cust_001": {
            "consentId": "consent-001",
            "customerId": "cust-001",
            "accountIds": ["cust-001-checking"],
            "dataClusters": ["ACCOUNTS", "TRANSACTIONS"],
            "expiresAt": null
          }
        }
    """
