"""Custom error types for Open Banking MCP."""

from __future__ import annotations


class OpenBankingError(Exception):
    """Base exception for all Open Banking MCP errors."""


class ConfigurationError(OpenBankingError):
    """Raised when a required configuration value is missing or invalid."""


class AuthenticationError(OpenBankingError):
    """Raised when authentication with the FDX API fails."""


class AuthorizationError(OpenBankingError):
    """Raised when a valid token requests data outside its consent scope.

    Distinct from :class:`AuthenticationError`: the token is known and unexpired, but the
    specific ``(account_id, data_cluster)`` combination the caller requested is not covered by
    the consent grant. Maps to an HTTP 403 Forbidden in an API context.

    Attributes:
        customer_id: The customer the token belongs to.
        reason: Human-readable explanation (e.g. ``"account not in consent scope"``).
        account_id: The requested account id, if applicable.
        cluster: The requested data cluster as a string, if applicable. Kept as ``str`` (not
            :class:`~banking_client.auth.clusters.DataCluster`) so ``common`` remains a leaf
            package with no dependency on the auth submodule.
    """

    def __init__(
        self,
        customer_id: str,
        reason: str,
        account_id: str | None = None,
        cluster: str | None = None,
    ) -> None:
        """Build a structured message from the rejection context."""
        parts = [f"customer={customer_id!r}", f"reason={reason!r}"]
        if account_id is not None:
            parts.append(f"account_id={account_id!r}")
        if cluster is not None:
            parts.append(f"cluster={cluster!r}")
        super().__init__(", ".join(parts))
        self.customer_id = customer_id
        self.reason = reason
        self.account_id = account_id
        self.cluster = cluster
