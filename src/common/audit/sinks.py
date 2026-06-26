"""Audit sinks — pluggable transport layer for emitting audit events.

The :class:`AuditSink` protocol is the Week-N swap seam: today the sink writes one JSON
line per event to stdout via a dedicated ``logging.Logger``; in production it would
forward to an immutable audit store (WORM S3 bucket, CloudTrail, a SIEM, …) by
implementing the same single-method protocol.

``StdoutJSONSink`` is intentionally thin: it does not format, transform, or redact. The
event is already a closed, redacted Pydantic model; the sink's only job is transport.

``ListSink`` is a test helper that captures events in memory. Deliberately kept in the
production module (not a separate test-only file) so every consumer of this package can
wire an in-memory sink without importing from test utilities.
"""

from __future__ import annotations

import logging
import sys
from typing import Protocol

from common.audit.events import AuditEvent

_AUDIT_LOGGER_NAME = "open_banking.audit"
"""Dedicated logger name.

Using a named logger (rather than the root logger) lets operators configure audit log
routing independently of application logs — e.g. direct it to a separate handler or log
group without filtering.
"""


class AuditSink(Protocol):
    """Protocol for audit event transport.

    Any class with a compatible ``emit`` method satisfies this protocol, enabling
    dependency injection without inheritance. The stub today is :class:`StdoutJSONSink`;
    production implementations (immutable audit store, SIEM, …) drop in transparently.
    """

    def emit(self, event: AuditEvent) -> None:
        """Persist or forward *event* to its destination.

        Implementations must be best-effort: they should not raise on transient failures
        in a way that propagates back to the caller and disrupts normal operation. In the
        stub, exceptions from the underlying logger do propagate (logging infrastructure
        failures are configuration bugs, not expected runtime failures).

        Args:
            event: The fully-constructed :class:`~common.audit.events.AuditEvent` to emit.
        """
        ...  # pragma: no cover


class StdoutJSONSink:
    """Emit each audit event as a single JSON line to stdout.

    Uses a dedicated ``logging.Logger`` (``open_banking.audit``) rather than ``print``
    so operators retain full stdlib-logging control over destination, level filtering, and
    log rotation. The logger is configured lazily and guarded against duplicate handlers
    so constructing multiple :class:`StdoutJSONSink` instances (e.g. once per request)
    is safe.

    Output format: one compact JSON object per line, using the event's camelCase
    :meth:`~pydantic.BaseModel.model_dump_json` serialisation. Parseable by ``jq``,
    CloudWatch Logs Insights, and any structured log aggregator.
    """

    def __init__(self) -> None:
        """Obtain (or lazily create) the dedicated audit logger."""
        self._logger = self._configure_logger()

    @staticmethod
    def _configure_logger() -> logging.Logger:
        """Return the audit logger, adding a StreamHandler only if none exists.

        The guard (``if not logger.handlers``) prevents duplicate lines when multiple
        :class:`StdoutJSONSink` instances are created in the same process.
        """
        logger = logging.getLogger(_AUDIT_LOGGER_NAME)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        return logger

    def emit(self, event: AuditEvent) -> None:
        """Write *event* as a single JSON line to stdout.

        Args:
            event: The audit event to emit.
        """
        self._logger.info(event.model_dump_json(by_alias=True))


class ListSink:
    """Capture audit events in memory.

    For use in tests and development tooling — inject a :class:`ListSink` instance into
    an :class:`~common.audit.trail.AuditTrail` and inspect :attr:`events` after the
    operation under test completes.

    Example::

        sink = ListSink()
        trail = AuditTrail(sink=sink)
        with trail.operation(action="get_transactions", actor=actor, resource=resource):
            ...
        assert len(sink.events) == 1
        assert sink.events[0].outcome == AuditOutcome.SUCCESS
    """

    def __init__(self) -> None:
        """Initialise with an empty event list."""
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        """Append *event* to :attr:`events`.

        Args:
            event: The audit event to capture.
        """
        self.events.append(event)
