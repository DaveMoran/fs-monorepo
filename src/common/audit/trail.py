"""Audit trail — correlation context and the operation context manager.

The audit trail has two public surfaces:

1. **Correlation** — a :func:`correlation` context manager and :func:`current_request_id`
   getter that use a :class:`~contextvars.ContextVar` to propagate a shared ``request_id``
   across all audit events in one logical request. Async-safe (each asyncio task inherits
   its own copy of the context, so concurrent requests do not share ids).

2. **Operation** — :meth:`AuditTrail.operation`, a context manager that wraps a
   data-access block and emits *exactly one* :class:`~common.audit.events.AuditEvent` on
   exit — :attr:`~common.audit.events.AuditOutcome.SUCCESS` (optionally annotated with
   ``result_count``) or :attr:`~common.audit.events.AuditOutcome.ERROR` (with
   ``error_type``) — before re-raising the exception. Timing is measured with
   :func:`time.perf_counter`.

The :class:`AuditTrail` accepts any :class:`~common.audit.sinks.AuditSink` at construction
time, defaulting to :class:`~common.audit.sinks.StdoutJSONSink` (stdout JSON line per event).
Swap in a :class:`~common.audit.sinks.ListSink` for tests.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from common.audit.events import AuditActor, AuditEvent, AuditOutcome, AuditResource
from common.audit.sinks import AuditSink, StdoutJSONSink

# ---------------------------------------------------------------------------
# Correlation context
# ---------------------------------------------------------------------------

_REQUEST_ID: ContextVar[str] = ContextVar("open_banking_request_id")
"""ContextVar holding the current request correlation id.

Async-safe: each asyncio Task inherits its parent's context at creation time, so
concurrent requests in different tasks do not share ids unless they explicitly share a
context object.
"""


@contextmanager
def correlation(request_id: str | None = None) -> Generator[str, None, None]:
    """Bind a correlation id for the duration of a ``with`` block.

    All :meth:`~AuditTrail.operation` calls within the block share the same
    ``request_id``, making it possible to correlate multi-step operations (e.g. a single
    MCP tool call that touches several accounts) in the audit log.

    Args:
        request_id: An explicit correlation id to use. If ``None``, a new UUID4 is
            generated automatically.

    Yields:
        The active ``request_id`` (either the supplied value or the generated one).

    Example::

        with correlation() as rid:
            scope = auth.authorize(token, account_id, DataCluster.ACCOUNTS)
            # Both operations below share `rid` in their audit events.
            await get_accounts(token)
            await get_transactions(token, account_id)
    """
    rid = request_id if request_id is not None else str(uuid4())
    token = _REQUEST_ID.set(rid)
    try:
        yield rid
    finally:
        _REQUEST_ID.reset(token)


def current_request_id() -> str:
    """Return the active correlation id, auto-generating one if none is set.

    When called outside a :func:`correlation` block, generates a fresh UUID4. This means
    two consecutive calls outside any block return *different* ids — they are not
    correlated. Use :func:`correlation` explicitly when you need to group events.

    Returns:
        The current ``request_id`` string.
    """
    try:
        return _REQUEST_ID.get()
    except LookupError:
        return str(uuid4())


# ---------------------------------------------------------------------------
# Operation handle
# ---------------------------------------------------------------------------


class OperationHandle:
    """Mutable handle yielded by :meth:`AuditTrail.operation`.

    Callers may set :attr:`result_count` inside the ``with`` block to annotate the event
    with how many items were returned — without attaching the actual items.

    Attributes:
        result_count: Count of items returned by the operation. ``None`` if not set.
        customer_id: Resolved FDX customer id, if the caller has it (e.g. after calling
            :meth:`~banking_client.auth.guard.Authorizer.authorize`). Overrides the
            ``customer_id`` supplied in *actor* when set; ``None`` leaves actor unchanged.
    """

    def __init__(self) -> None:
        """Initialise with all optional attributes set to ``None``."""
        self.result_count: int | None = None
        self.customer_id: str | None = None


# ---------------------------------------------------------------------------
# AuditTrail
# ---------------------------------------------------------------------------


class AuditTrail:
    """Wraps data-access blocks and emits exactly one audit event per operation.

    Args:
        sink: The :class:`~common.audit.sinks.AuditSink` to emit events to. Defaults to
            :class:`~common.audit.sinks.StdoutJSONSink`. Inject a
            :class:`~common.audit.sinks.ListSink` in tests.

    Example — direct usage::

        sink = ListSink()
        trail = AuditTrail(sink=sink)
        actor = AuditActor(token_id=token_fingerprint(raw_token), customer_id="cust-001")
        resource = AuditResource(account_ids=("cust-001-checking",), data_cluster="ACCOUNTS")
        with trail.operation(action="get_accounts", actor=actor, resource=resource) as h:
            accounts = fetch_accounts("cust-001-checking")
            h.result_count = len(accounts)
    """

    def __init__(self, sink: AuditSink | None = None) -> None:
        """Bind the sink, defaulting to StdoutJSONSink."""
        self._sink: AuditSink = sink if sink is not None else StdoutJSONSink()

    @contextmanager
    def operation(
        self,
        *,
        action: str,
        actor: AuditActor,
        resource: AuditResource,
    ) -> Generator[OperationHandle, None, None]:
        """Context manager that audits one data-access block.

        Emits **exactly one** :class:`~common.audit.events.AuditEvent` when the ``with``
        block exits — regardless of whether it exits normally or via exception. On
        exception the event has ``outcome=ERROR`` and ``error_type`` set to the exception
        class name; the exception is re-raised after emission.

        The yielded :class:`OperationHandle` allows the caller to annotate the event with
        ``result_count`` and/or a resolved ``customer_id`` before the block exits.

        Args:
            action: Logical operation name (e.g. ``"get_transactions"``).
            actor: Who initiated the request.
            resource: What data was requested.

        Yields:
            :class:`OperationHandle` — set ``handle.result_count`` and/or
            ``handle.customer_id`` inside the block.

        Raises:
            Exception: Re-raises any exception that propagated out of the ``with`` block,
                after emitting the error audit event.
        """
        handle = OperationHandle()
        start = time.perf_counter()
        error: Exception | None = None

        try:
            yield handle
        except Exception as exc:
            error = exc
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 3)

            # Merge resolved customer_id from the handle (post-authorize path).
            resolved_actor = (
                AuditActor(
                    token_id=actor.token_id,
                    customer_id=handle.customer_id,
                )
                if handle.customer_id is not None
                else actor
            )

            event = AuditEvent(
                request_id=current_request_id(),
                actor=resolved_actor,
                action=action,
                resource=resource,
                outcome=AuditOutcome.ERROR if error is not None else AuditOutcome.SUCCESS,
                error_type=type(error).__name__ if error is not None else None,
                result_count=handle.result_count,
                duration_ms=duration_ms,
            )
            self._sink.emit(event)
