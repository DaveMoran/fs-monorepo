"""``@audited`` decorator — wraps a data-access function so it cannot skip audit logging.

The decorator is the "can't forget" enforcement mechanism. Applying ``@audited(...)`` to a
banking-client wrapper function means the audit event is emitted automatically on every
call — the developer does not need to remember to open an :meth:`~trail.AuditTrail.operation`
context manager inside each wrapper.

Usage
-----
Sync::

    @audited("get_accounts", data_cluster="ACCOUNTS")
    def get_accounts(token: str, account_id: str) -> list[Account]:
        ...

Async (auto-detected)::

    @audited("get_transactions", data_cluster="TRANSACTIONS")
    async def get_transactions(token: str, account_id: str) -> PaginatedResponse[Transaction]:
        ...

The decorator extracts the actor token fingerprint and the resource account id(s) from
the function's bound arguments at call time. ``customer_id`` is not extracted by the
decorator (it is only known *after* token resolution inside the function body); callers
that need ``customer_id`` in the event should use :meth:`~trail.AuditTrail.operation`
directly and set ``handle.customer_id`` after the authorize call.

Parameters
----------
action:
    Logical operation name for the audit event (e.g. ``"get_transactions"``).
data_cluster:
    Optional data-cluster label (e.g. ``"TRANSACTIONS"``). Pass a
    :class:`~banking_client.auth.clusters.DataCluster` value — it is a
    :class:`~enum.StrEnum`, so it is already a ``str``.
token_arg:
    Name of the parameter in the wrapped function that carries the bearer token.
    Defaults to ``"token"``.
account_id_arg:
    Name of the parameter in the wrapped function that carries the account id(s).
    Accepts a scalar ``str`` or a sequence. Defaults to ``"account_id"``.
trail:
    :class:`~trail.AuditTrail` instance to use. Defaults to a module-level trail
    backed by :class:`~sinks.StdoutJSONSink`. Override in tests by passing an
    ``AuditTrail(sink=ListSink())``.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from common.audit.events import AuditActor, AuditResource, token_fingerprint
from common.audit.trail import AuditTrail

_F = TypeVar("_F", bound=Callable[..., Any])

# Module-level default trail; one StdoutJSONSink shared across all @audited decorators
# unless overridden per-decorator. Instantiated lazily on first decorator creation.
_default_trail: AuditTrail | None = None


def _get_default_trail() -> AuditTrail:
    global _default_trail
    if _default_trail is None:
        _default_trail = AuditTrail()
    return _default_trail


def audited(
    action: str,
    *,
    data_cluster: str | None = None,
    token_arg: str = "token",
    account_id_arg: str = "account_id",
    trail: AuditTrail | None = None,
) -> Callable[[_F], _F]:
    """Return a decorator that wraps a data-access function with automatic audit logging.

    The decorator inspects the wrapped function's call signature at decoration time and
    binds the actual arguments at each call to extract the token and account id(s). It
    handles both sync and async functions transparently.

    Args:
        action: Logical operation name recorded in the audit event.
        data_cluster: Data-cluster label for :class:`~events.AuditResource`. ``None``
            is valid for non-FDX operations.
        token_arg: Name of the bearer-token parameter. Must be present in the wrapped
            function's signature for actor extraction; if absent, ``token_id`` is set to
            ``"<no-token>"``.
        account_id_arg: Name of the account-id parameter. Scalar ``str`` or sequence of
            ``str``. If absent, ``account_ids`` is an empty tuple.
        trail: :class:`~trail.AuditTrail` to use. Defaults to the module-level trail
            backed by :class:`~sinks.StdoutJSONSink`.

    Returns:
        A decorator preserving the wrapped function's type signature.
    """

    def decorator(fn: _F) -> _F:
        sig = inspect.signature(fn)
        _trail = trail if trail is not None else _get_default_trail()

        def _build_actor_resource(*args: Any, **kwargs: Any) -> tuple[AuditActor, AuditResource]:
            """Extract actor and resource from bound call arguments."""
            arguments: dict[str, Any]
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                arguments = dict(bound.arguments)
            except TypeError:
                arguments = {}

            raw_token = arguments.get(token_arg, "")
            tid = token_fingerprint(str(raw_token)) if raw_token else "<no-token>"
            actor = AuditActor(token_id=tid)

            raw_account = arguments.get(account_id_arg)
            if isinstance(raw_account, str):
                account_ids: tuple[str, ...] = (raw_account,)
            elif isinstance(raw_account, (list, tuple)):
                account_ids = tuple(str(a) for a in raw_account)
            else:
                account_ids = ()

            resource = AuditResource(account_ids=account_ids, data_cluster=data_cluster)
            return actor, resource

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                actor, resource = _build_actor_resource(*args, **kwargs)
                with _trail.operation(action=action, actor=actor, resource=resource) as handle:
                    result = await fn(*args, **kwargs)
                    with contextlib.suppress(TypeError):
                        handle.result_count = len(result)
                    return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            actor, resource = _build_actor_resource(*args, **kwargs)
            with _trail.operation(action=action, actor=actor, resource=resource) as handle:
                result = fn(*args, **kwargs)
                with contextlib.suppress(TypeError):
                    handle.result_count = len(result)
                return result

        return sync_wrapper  # type: ignore[return-value]

    return decorator
