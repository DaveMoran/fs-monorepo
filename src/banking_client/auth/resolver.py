"""Consent resolver — the Week 20 OAuth swap seam.

The :class:`ConsentResolver` :class:`~typing.Protocol` defines the single method any resolver
must satisfy: given an opaque bearer token string, return the :class:`~banking_client.auth.scope.ConsentScope`
it unlocks, or raise :class:`~common.errors.AuthenticationError` if the token is unknown or
expired.

Today's implementation — :class:`FixtureConsentResolver` — reads the committed
``fixtures/data/consents.json`` once at construction time and serves lookups from memory.

Week 20 swap
------------
Replace :class:`FixtureConsentResolver` with an ``OAuthConsentResolver`` that validates the
bearer JWT against the authorization server's JWKS endpoint, introspects the token to retrieve
the FDX consent grant, and maps the granted OAuth scopes + consent record into the **same**
:class:`~banking_client.auth.scope.ConsentScope`. Only :func:`~banking_client.auth.guard.default_authorizer`
(one line) needs to change; the :class:`~banking_client.auth.guard.Authorizer`, all error
types, and every caller are untouched.

The protocol is structural (duck-typed) — ``OAuthConsentResolver`` does not need to inherit
anything; it merely needs a ``resolve(token: str) -> ConsentScope`` method with the correct
signature.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from banking_client.auth.scope import ConsentRegistry, ConsentScope
from common.errors import AuthenticationError


class ConsentResolver(Protocol):
    """Structural protocol for resolving a bearer token to its consent scope.

    Any class with a compatible ``resolve`` method satisfies this protocol, enabling
    dependency injection without inheritance. The stub today is
    :class:`FixtureConsentResolver`; the production implementation will be an OAuth-backed
    class that satisfies the same protocol.
    """

    def resolve(self, token: str) -> ConsentScope:
        """Return the :class:`~banking_client.auth.scope.ConsentScope` for *token*.

        Args:
            token: Opaque bearer token string from the ``Authorization: Bearer …`` header.

        Returns:
            The consent scope associated with *token*.

        Raises:
            AuthenticationError: If *token* is not recognised or has expired.
        """
        ...  # pragma: no cover


class FixtureConsentResolver:
    """Resolves bearer tokens from the committed ``consents.json`` fixture.

    Loads and parses the registry once at construction time; subsequent calls are in-memory
    lookups. Suitable for development, tests, and the MCP dev server only — not for
    production.

    Args:
        path: Filesystem path to a ``consents.json`` file conforming to
            :class:`~banking_client.auth.scope.ConsentRegistry`.
        now: Zero-argument callable returning the current UTC datetime. Defaults to
            ``lambda: datetime.now(UTC)``. Injecting a fixed value in tests keeps expiry
            assertions deterministic without patching ``datetime``.

    Example::

        resolver = FixtureConsentResolver(default_consent_path())
        scope = resolver.resolve("tok_cust_001")
        print(scope.customer_id)  # "cust-001"
    """

    def __init__(
        self,
        path: Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Load and parse the consent registry from *path*."""
        self._registry: ConsentRegistry = ConsentRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        self._now: Callable[[], datetime] = now if now is not None else lambda: datetime.now(UTC)

    def resolve(self, token: str) -> ConsentScope:
        """Look up *token* and return its scope, raising on unknown or expired tokens.

        Args:
            token: Opaque bearer token string.

        Returns:
            The :class:`~banking_client.auth.scope.ConsentScope` for *token*.

        Raises:
            AuthenticationError: If *token* is not in the registry, or if the scope's
                ``expires_at`` is set and the current time is at or past it.
        """
        scope: ConsentScope | None = self._registry.root.get(token)
        if scope is None:
            raise AuthenticationError(f"Unknown bearer token: {token!r}")
        if scope.expires_at is not None and self._now() >= scope.expires_at:
            raise AuthenticationError(f"Bearer token {token!r} has expired")
        return scope


def default_consent_path() -> Path:
    """Return the path to the committed ``fixtures/data/consents.json``.

    Resolves relative to this file's location: ``src/banking_client/auth/resolver.py``
    is three directories below the repo root, so ``parents[3]`` reaches the repo root.
    This helper is a *development convenience* — it disappears when the OAuth resolver
    replaces the fixture stub.

    Returns:
        Absolute path to ``<repo_root>/fixtures/data/consents.json``.
    """
    return Path(__file__).resolve().parents[3] / "fixtures" / "data" / "consents.json"
