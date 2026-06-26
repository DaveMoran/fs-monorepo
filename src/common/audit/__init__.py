"""Structured audit-trail layer for the Open Banking MCP system.

Every data-access call to a financial institution must emit a structured audit event
capturing who requested what, when, and with what outcome — and must never capture raw
financial data. This package provides the full stack:

- :class:`AuditEvent` / :class:`AuditActor` / :class:`AuditResource` / :class:`AuditOutcome`
  — the closed, versioned compliance schema (``extra="forbid"``; no payload field possible).
- :func:`token_fingerprint` — one-way token pseudonymisation.
- :class:`AuditSink` Protocol + :class:`StdoutJSONSink` / :class:`ListSink` — pluggable transport.
- :func:`correlation` / :func:`current_request_id` — async-safe request-id propagation.
- :class:`AuditTrail` / :class:`OperationHandle` — the core context manager; exactly one event per block.
- :func:`audited` — decorator that wraps a data-access function so it cannot skip audit logging.
"""

from __future__ import annotations

from common.audit.decorator import audited
from common.audit.events import AuditActor, AuditEvent, AuditOutcome, AuditResource, token_fingerprint
from common.audit.sinks import AuditSink, ListSink, StdoutJSONSink
from common.audit.trail import AuditTrail, OperationHandle, correlation, current_request_id

__all__: list[str] = [
    "AuditActor",
    "AuditEvent",
    "AuditOutcome",
    "AuditResource",
    "AuditSink",
    "AuditTrail",
    "ListSink",
    "OperationHandle",
    "StdoutJSONSink",
    "audited",
    "correlation",
    "current_request_id",
    "token_fingerprint",
]
