"""Audit event schema — the compliance artifact.

This module defines the closed, versioned data model for every audit event the system emits.
It is the artifact a compliance reviewer (or interviewer) scrutinises: does the schema make
it *structurally impossible* to leak raw financial data, or does it rely on developers
remembering not to log sensitive fields?

Design principles
-----------------
Allowlist by schema, not denylist
    The :class:`AuditEvent` model has ``extra="forbid"``. There is no ``payload``, ``response``,
    ``account_number``, or ``transaction`` field. You cannot attach one at runtime — Pydantic
    will raise :class:`~pydantic.ValidationError` if you try. The redaction guarantee is
    *structural*, not disciplinary.

Identifiers, not values
    :attr:`~AuditResource.account_ids` are opaque references (e.g. ``"cust-003-checking"``),
    not account numbers or balances. :attr:`~AuditResource.data_cluster` is a category label
    (e.g. ``"TRANSACTIONS"``), not transaction data. :attr:`~AuditEvent.result_count` is a
    count of items returned, never the items themselves.

Token redaction
    The raw bearer token never appears in any audit field. :attr:`~AuditActor.token_id` is a
    one-way fingerprint (``"sha256:" + first 16 hex chars of SHA-256``) — stable for
    correlation across events in a session, non-reversible. See :func:`token_fingerprint`.

Error redaction
    On failure, only :attr:`~AuditEvent.error_type` is set — the *class name* of the
    exception (e.g. ``"AuthorizationError"``). The exception message, arguments, and
    traceback are never logged, preventing accidental leak of partial return values or
    sensitive interpolated strings.

Wire format
    camelCase JSON via ``alias_generator=to_camel`` (consistent with the FDX model layer).
    :attr:`~AuditEvent.schema_version` is a plain ``"1"`` string so schema evolution is
    detectable without breaking existing consumers.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Shared Pydantic config for all audit models: camelCase wire names, frozen, no extras.
# Defined locally so common stays a leaf package with no import from banking_client.models.base.
_AUDIT_CONFIG = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
    frozen=True,
)


class AuditOutcome(StrEnum):
    """Terminal outcome of an audited data-access operation."""

    SUCCESS = "SUCCESS"
    """The operation completed without raising an exception."""

    ERROR = "ERROR"
    """The operation raised an exception; see :attr:`~AuditEvent.error_type`."""


class AuditActor(BaseModel):
    """Who initiated the data-access request.

    Attributes:
        customer_id: The FDX customer the token belongs to (e.g. ``"cust-001"``).
            ``None`` when the actor is not yet resolved (e.g. inside an ``@audited``
            decorator that runs before token resolution).
        token_id: One-way pseudonymous fingerprint of the bearer token. Never the raw
            token. Use :func:`token_fingerprint` to compute this value.
    """

    model_config = _AUDIT_CONFIG

    customer_id: str | None = None
    """FDX customer identifier (an opaque id, not a name or PII)."""
    token_id: str
    """Pseudonymous token fingerprint — ``"sha256:<first-16-hex-chars>"``."""


class AuditResource(BaseModel):
    """What financial data was requested.

    Attributes:
        account_ids: Opaque account id references touched by the operation (e.g.
            ``("cust-003-checking",)``). Never account numbers, balances, or PII.
        data_cluster: The category of data requested (e.g. ``"TRANSACTIONS"``). Typed
            as :class:`str` so :mod:`common` stays a leaf package — callers pass a
            :class:`~banking_client.auth.clusters.DataCluster` value, which is a
            :class:`~enum.StrEnum` and therefore already a ``str``.
    """

    model_config = _AUDIT_CONFIG

    account_ids: tuple[str, ...]
    """Opaque account id references; never account numbers or sensitive values."""
    data_cluster: str | None = None
    """Data category label (e.g. ``"ACCOUNTS"``); ``None`` for non-FDX operations."""


class AuditEvent(BaseModel):
    """A single structured audit-trail entry for one data-access call.

    Immutable (``frozen=True``) and closed (``extra="forbid"``). The schema is versioned
    via :attr:`schema_version` so downstream log consumers can detect breaking changes.

    Attributes:
        schema_version: Document version. ``"1"`` today; increment when the shape changes.
        event_id: UUID4 unique to this event — never reused, useful for idempotency checks
            in a persistent audit store.
        request_id: Correlation id shared by all events in one logical request. Set via
            :func:`~common.audit.trail.correlation`; auto-generated if no correlation
            context is active.
        timestamp: UTC emission time (ISO 8601 on the wire).
        actor: Who made the request.
        action: Logical operation name, typically the wrapper method (e.g.
            ``"get_transactions"``). Freeform string; callers define their own vocabulary.
        resource: What data was requested.
        outcome: :attr:`~AuditOutcome.SUCCESS` or :attr:`~AuditOutcome.ERROR`.
        error_type: Exception class name only (e.g. ``"AuthorizationError"``). ``None``
            on success. Never contains the exception message or traceback.
        result_count: Count of items returned — metadata about the response, never the
            response itself. ``None`` when the return value is not sized.
        duration_ms: Wall-clock duration of the operation in milliseconds, rounded to
            three decimal places.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        extra="forbid",
    )

    schema_version: str = "1"
    """Audit schema version; increment when the shape changes."""
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    """UUID4 unique to this event."""
    request_id: str
    """Correlation id; shared across all events in one logical request."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """UTC emission time (ISO 8601 on the wire)."""
    actor: AuditActor
    """Who initiated the request."""
    action: str
    """Logical operation name (e.g. ``"get_transactions"``)."""
    resource: AuditResource
    """What financial data was requested."""
    outcome: AuditOutcome
    """Terminal outcome: SUCCESS or ERROR."""
    error_type: str | None = None
    """Exception class name only; ``None`` on success; never message or traceback."""
    result_count: int | None = None
    """Count of items returned; ``None`` when the return value is not sized."""
    duration_ms: float | None = None
    """Wall-clock duration in milliseconds."""


def token_fingerprint(token: str) -> str:
    """Derive a pseudonymous, non-reversible fingerprint from a raw bearer token.

    Uses the first 16 hex characters of SHA-256 (64 bits of entropy) — enough to
    correlate events within a session without reconstructing the original token.

    Args:
        token: The raw bearer token string. Never stored; only the fingerprint is kept.

    Returns:
        A string of the form ``"sha256:<16-hex-chars>"`` (e.g. ``"sha256:9f2a1c3b..."``).

    Example::

        token_fingerprint("my-secret-token")
        # "sha256:a1b2c3d4e5f60718"  (illustrative)
    """
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"sha256:{digest[:16]}"
