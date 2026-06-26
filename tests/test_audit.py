"""Tests for the structured audit-trail layer.

Covers: AuditEvent schema and redaction guarantees, token_fingerprint, StdoutJSONSink
(JSON line output, no duplicate handlers), ListSink, correlation context, AuditTrail
operation CM (exactly one event, result_count handle, customer_id override), @audited
decorator (sync + async, success + error), and the compliance proofs (no sensitive leak,
extra="forbid" schema closure).
"""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from common.audit import (
    AuditActor,
    AuditEvent,
    AuditOutcome,
    AuditResource,
    AuditTrail,
    ListSink,
    OperationHandle,
    StdoutJSONSink,
    audited,
    correlation,
    current_request_id,
    token_fingerprint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RAW_TOKEN = "super-secret-bearer-token-abc123"
_ACCOUNT_ID = "cust-001-checking"


def _actor(customer_id: str | None = "cust-001") -> AuditActor:
    return AuditActor(token_id=token_fingerprint(_RAW_TOKEN), customer_id=customer_id)


def _resource(account_id: str = _ACCOUNT_ID, cluster: str | None = "ACCOUNTS") -> AuditResource:
    return AuditResource(account_ids=(account_id,), data_cluster=cluster)


def _trail() -> tuple[AuditTrail, ListSink]:
    sink = ListSink()
    return AuditTrail(sink=sink), sink


# ---------------------------------------------------------------------------
# token_fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_starts_with_sha256_prefix() -> None:
    """token_fingerprint returns a string starting with 'sha256:'."""
    fp = token_fingerprint(_RAW_TOKEN)
    assert fp.startswith("sha256:")


def test_fingerprint_does_not_contain_raw_token() -> None:
    """token_fingerprint output never contains the raw token string."""
    fp = token_fingerprint(_RAW_TOKEN)
    assert _RAW_TOKEN not in fp


def test_fingerprint_is_deterministic() -> None:
    """Same token always produces same fingerprint."""
    assert token_fingerprint(_RAW_TOKEN) == token_fingerprint(_RAW_TOKEN)


def test_fingerprint_length() -> None:
    """Fingerprint is 'sha256:' + 16 hex chars = 23 chars total."""
    assert len(token_fingerprint(_RAW_TOKEN)) == len("sha256:") + 16


def test_fingerprint_differs_across_tokens() -> None:
    """Different tokens produce different fingerprints."""
    assert token_fingerprint("token-a") != token_fingerprint("token-b")


# ---------------------------------------------------------------------------
# AuditEvent schema — closure and redaction
# ---------------------------------------------------------------------------


def test_audit_event_extra_forbid_rejects_payload_field() -> None:
    """extra='forbid' makes it structurally impossible to attach a payload field."""
    with pytest.raises(ValidationError):
        AuditEvent(  # type: ignore[call-arg]
            request_id="req-1",
            actor=_actor(),
            action="get_accounts",
            resource=_resource(),
            outcome=AuditOutcome.SUCCESS,
            payload="sensitive-financial-data",
        )


def test_audit_event_is_frozen() -> None:
    """AuditEvent is immutable after construction."""
    event = AuditEvent(
        request_id="req-1",
        actor=_actor(),
        action="get_accounts",
        resource=_resource(),
        outcome=AuditOutcome.SUCCESS,
    )
    with pytest.raises(ValidationError):
        event.action = "mutated"  # type: ignore[misc]


def test_audit_event_json_keys_are_camel_case() -> None:
    """AuditEvent serializes with camelCase keys matching FDX wire convention."""
    event = AuditEvent(
        request_id="req-1",
        actor=_actor(),
        action="get_accounts",
        resource=_resource(),
        outcome=AuditOutcome.SUCCESS,
    )
    data = json.loads(event.model_dump_json(by_alias=True))
    assert "schemaVersion" in data
    assert "eventId" in data
    assert "requestId" in data
    assert "errorType" in data
    assert "schema_version" not in data


def test_audit_event_schema_version_is_one() -> None:
    """Default schema_version is '1'."""
    event = AuditEvent(
        request_id="r",
        actor=_actor(),
        action="a",
        resource=_resource(),
        outcome=AuditOutcome.SUCCESS,
    )
    assert event.schema_version == "1"


def test_audit_event_timestamp_is_utc() -> None:
    """Default timestamp is UTC-aware."""
    event = AuditEvent(
        request_id="r",
        actor=_actor(),
        action="a",
        resource=_resource(),
        outcome=AuditOutcome.SUCCESS,
    )
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_audit_event_raw_token_not_in_json() -> None:
    """Serialized event JSON must not contain the raw bearer token."""
    event = AuditEvent(
        request_id="req-1",
        actor=_actor(),
        action="get_transactions",
        resource=_resource(),
        outcome=AuditOutcome.SUCCESS,
    )
    serialized = event.model_dump_json(by_alias=True)
    assert _RAW_TOKEN not in serialized


def test_audit_event_token_id_is_fingerprint() -> None:
    """actor.token_id is the sha256 fingerprint, never the raw token."""
    event = AuditEvent(
        request_id="req-1",
        actor=_actor(),
        action="get_accounts",
        resource=_resource(),
        outcome=AuditOutcome.SUCCESS,
    )
    assert event.actor.token_id.startswith("sha256:")
    assert _RAW_TOKEN not in event.actor.token_id


def test_audit_resource_has_no_account_number_field() -> None:
    """AuditResource has account_ids (opaque ids), not account numbers."""
    r = _resource()
    assert hasattr(r, "account_ids")
    assert not hasattr(r, "account_number")
    assert not hasattr(r, "balance")
    assert not hasattr(r, "transactions")


# ---------------------------------------------------------------------------
# correlation and current_request_id
# ---------------------------------------------------------------------------


def test_correlation_provides_shared_request_id() -> None:
    """Events emitted inside one correlation() block share request_id."""
    trail, sink = _trail()
    with correlation() as rid:
        with trail.operation(action="a", actor=_actor(), resource=_resource()):
            pass
        with trail.operation(action="b", actor=_actor(), resource=_resource()):
            pass
    assert len(sink.events) == 2
    assert sink.events[0].request_id == rid
    assert sink.events[1].request_id == rid


def test_distinct_correlation_blocks_differ() -> None:
    """Events from different correlation() blocks have different request_ids."""
    trail, sink = _trail()
    with correlation(), trail.operation(action="a", actor=_actor(), resource=_resource()):
        pass
    with correlation(), trail.operation(action="b", actor=_actor(), resource=_resource()):
        pass
    assert sink.events[0].request_id != sink.events[1].request_id


def test_explicit_correlation_id_is_used() -> None:
    """Explicit request_id passed to correlation() appears in events."""
    trail, sink = _trail()
    with correlation(request_id="my-trace-id"), trail.operation(action="a", actor=_actor(), resource=_resource()):
        pass
    assert sink.events[0].request_id == "my-trace-id"


def test_current_request_id_auto_generates_outside_context() -> None:
    """current_request_id() returns a non-empty string even outside any correlation block."""
    rid = current_request_id()
    assert isinstance(rid, str)
    assert len(rid) > 0


# ---------------------------------------------------------------------------
# AuditTrail.operation — context manager
# ---------------------------------------------------------------------------


def test_operation_emits_exactly_one_event_on_success() -> None:
    """A successful operation block emits exactly one SUCCESS event."""
    trail, sink = _trail()
    with trail.operation(action="get_accounts", actor=_actor(), resource=_resource()):
        pass
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.SUCCESS


def test_operation_emits_exactly_one_event_on_error() -> None:
    """A failing operation block emits exactly one ERROR event before re-raising."""
    trail, sink = _trail()
    with pytest.raises(ValueError), trail.operation(action="get_accounts", actor=_actor(), resource=_resource()):
        raise ValueError("something went wrong")
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.ERROR


def test_operation_error_type_is_class_name_only() -> None:
    """error_type contains only the exception class name — not the message."""
    trail, sink = _trail()

    class SensitiveError(Exception):
        pass

    with pytest.raises(SensitiveError), trail.operation(action="a", actor=_actor(), resource=_resource()):
        raise SensitiveError("account number: 4111111111111111")
    event = sink.events[0]
    assert event.error_type == "SensitiveError"
    # The exception message (which could contain sensitive data) must NOT appear.
    serialized = event.model_dump_json(by_alias=True)
    assert "4111111111111111" not in serialized


def test_operation_exception_propagates() -> None:
    """Exception raised inside operation() propagates to the caller."""
    trail, sink = _trail()
    op_ctx = trail.operation(action="a", actor=_actor(), resource=_resource())
    with pytest.raises(RuntimeError, match="propagated"), op_ctx:
        raise RuntimeError("propagated")


def test_operation_result_count_via_handle() -> None:
    """Setting handle.result_count inside the block appears in the emitted event."""
    trail, sink = _trail()
    with trail.operation(action="get_txns", actor=_actor(), resource=_resource()) as handle:
        handle.result_count = 42
    assert sink.events[0].result_count == 42


def test_operation_customer_id_override_via_handle() -> None:
    """Setting handle.customer_id inside the block overrides the actor's customer_id."""
    trail, sink = _trail()
    initial_actor = AuditActor(token_id=token_fingerprint(_RAW_TOKEN), customer_id=None)
    with trail.operation(action="a", actor=initial_actor, resource=_resource()) as handle:
        handle.customer_id = "cust-001"
    assert sink.events[0].actor.customer_id == "cust-001"


def test_operation_duration_ms_is_set() -> None:
    """Emitted event always has a non-negative duration_ms."""
    trail, sink = _trail()
    with trail.operation(action="a", actor=_actor(), resource=_resource()):
        pass
    assert sink.events[0].duration_ms is not None
    assert sink.events[0].duration_ms >= 0


def test_operation_action_and_resource_in_event() -> None:
    """Action and resource fields are faithfully recorded in the event."""
    trail, sink = _trail()
    resource = AuditResource(account_ids=("cust-002-savings",), data_cluster="TRANSACTIONS")
    with trail.operation(action="get_transactions", actor=_actor(), resource=resource):
        pass
    event = sink.events[0]
    assert event.action == "get_transactions"
    assert "cust-002-savings" in event.resource.account_ids
    assert event.resource.data_cluster == "TRANSACTIONS"


# ---------------------------------------------------------------------------
# @audited decorator — sync
# ---------------------------------------------------------------------------


def test_audited_sync_success_emits_one_event() -> None:
    """@audited on a sync function emits exactly one SUCCESS event per call."""
    sink = ListSink()
    trail = AuditTrail(sink=sink)

    @audited("get_accounts", data_cluster="ACCOUNTS", trail=trail)
    def get_accounts(token: str, account_id: str) -> list[str]:
        return ["item-1", "item-2"]

    result = get_accounts(_RAW_TOKEN, _ACCOUNT_ID)
    assert result == ["item-1", "item-2"]
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.SUCCESS


def test_audited_sync_sets_result_count() -> None:
    """@audited sets result_count from len() of the return value."""
    sink = ListSink()
    trail = AuditTrail(sink=sink)

    @audited("get_accounts", trail=trail)
    def get_accounts(token: str, account_id: str) -> list[str]:
        return ["a", "b", "c"]

    get_accounts(_RAW_TOKEN, _ACCOUNT_ID)
    assert sink.events[0].result_count == 3


def test_audited_sync_error_emits_error_event() -> None:
    """@audited on a sync function emits ERROR event and re-raises on exception."""
    sink = ListSink()
    trail = AuditTrail(sink=sink)

    @audited("get_accounts", trail=trail)
    def get_accounts(token: str, account_id: str) -> list[str]:
        raise PermissionError("denied")

    with pytest.raises(PermissionError):
        get_accounts(_RAW_TOKEN, _ACCOUNT_ID)
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.ERROR
    assert sink.events[0].error_type == "PermissionError"


def test_audited_sync_extracts_token_fingerprint() -> None:
    """@audited extracts token and stores only the sha256 fingerprint."""
    sink = ListSink()
    trail = AuditTrail(sink=sink)

    @audited("op", trail=trail)
    def op(token: str, account_id: str) -> None:
        pass

    op(_RAW_TOKEN, _ACCOUNT_ID)
    event = sink.events[0]
    assert event.actor.token_id.startswith("sha256:")
    serialized = event.model_dump_json(by_alias=True)
    assert _RAW_TOKEN not in serialized


def test_audited_sync_extracts_account_id() -> None:
    """@audited populates resource.account_ids from the account_id argument."""
    sink = ListSink()
    trail = AuditTrail(sink=sink)

    @audited("op", data_cluster="TRANSACTIONS", trail=trail)
    def op(token: str, account_id: str) -> None:
        pass

    op(_RAW_TOKEN, "cust-003-checking")
    event = sink.events[0]
    assert "cust-003-checking" in event.resource.account_ids
    assert event.resource.data_cluster == "TRANSACTIONS"


def test_audited_multiple_calls_each_get_own_event() -> None:
    """Two consecutive calls produce two independent events."""
    sink = ListSink()
    trail = AuditTrail(sink=sink)

    @audited("op", trail=trail)
    def op(token: str, account_id: str) -> None:
        pass

    op(_RAW_TOKEN, _ACCOUNT_ID)
    op(_RAW_TOKEN, _ACCOUNT_ID)
    assert len(sink.events) == 2
    assert sink.events[0].event_id != sink.events[1].event_id


# ---------------------------------------------------------------------------
# @audited decorator — async
# ---------------------------------------------------------------------------


async def test_audited_async_success_emits_one_event() -> None:
    """@audited on an async function emits exactly one SUCCESS event per call."""
    sink = ListSink()
    trail = AuditTrail(sink=sink)

    @audited("get_transactions", data_cluster="TRANSACTIONS", trail=trail)
    async def get_transactions(token: str, account_id: str) -> list[str]:
        return ["txn-1", "txn-2", "txn-3"]

    result = await get_transactions(_RAW_TOKEN, _ACCOUNT_ID)
    assert result == ["txn-1", "txn-2", "txn-3"]
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.SUCCESS
    assert sink.events[0].result_count == 3


async def test_audited_async_error_emits_error_event() -> None:
    """@audited on an async function emits ERROR and re-raises on exception."""
    sink = ListSink()
    trail = AuditTrail(sink=sink)

    @audited("get_transactions", trail=trail)
    async def get_transactions(token: str, account_id: str) -> list[str]:
        raise TimeoutError("upstream timeout")

    with pytest.raises(TimeoutError):
        await get_transactions(_RAW_TOKEN, _ACCOUNT_ID)
    assert len(sink.events) == 1
    assert sink.events[0].outcome == AuditOutcome.ERROR
    assert sink.events[0].error_type == "TimeoutError"


# ---------------------------------------------------------------------------
# StdoutJSONSink
# ---------------------------------------------------------------------------


def test_stdout_sink_emits_parseable_json(capsys: pytest.CaptureFixture[str]) -> None:
    """StdoutJSONSink writes one parseable JSON line per event to stdout."""
    sink = StdoutJSONSink()
    event = AuditEvent(
        request_id="req-stdout",
        actor=_actor(),
        action="get_accounts",
        resource=_resource(),
        outcome=AuditOutcome.SUCCESS,
    )
    sink.emit(event)
    captured = capsys.readouterr()
    line = captured.out.strip()
    parsed = json.loads(line)
    assert parsed["requestId"] == "req-stdout"
    assert parsed["outcome"] == "SUCCESS"


def test_stdout_sink_no_duplicate_handlers() -> None:
    """Constructing multiple StdoutJSONSink instances doesn't add duplicate handlers."""
    # Remove any handlers set by prior test runs to get a clean baseline.
    audit_logger = logging.getLogger("open_banking.audit")
    audit_logger.handlers.clear()

    StdoutJSONSink()
    StdoutJSONSink()
    StdoutJSONSink()

    assert len(audit_logger.handlers) == 1


# ---------------------------------------------------------------------------
# OperationHandle exported correctly
# ---------------------------------------------------------------------------


def test_operation_handle_is_exported() -> None:
    """OperationHandle is importable from common.audit."""
    assert OperationHandle is not None
    h = OperationHandle()
    assert h.result_count is None
    assert h.customer_id is None


# ---------------------------------------------------------------------------
# Compliance: sensitive data never leaks across all paths
# ---------------------------------------------------------------------------


def test_error_message_not_in_serialized_event() -> None:
    """Exception message (potentially containing sensitive data) never appears in JSON."""
    trail, sink = _trail()
    sensitive_message = "balance=12345.67 account=4111111111111111"
    with pytest.raises(ValueError), trail.operation(action="a", actor=_actor(), resource=_resource()):
        raise ValueError(sensitive_message)
    serialized = sink.events[0].model_dump_json(by_alias=True)
    assert sensitive_message not in serialized
    assert "4111111111111111" not in serialized


def test_extra_forbid_blocks_any_payload_field() -> None:
    """Constructing AuditEvent with any unknown field raises ValidationError."""
    for field_name in ("payload", "response", "account_number", "transaction_data", "ssn"):
        with pytest.raises(ValidationError):
            AuditEvent(  # type: ignore[call-arg]
                request_id="r",
                actor=_actor(),
                action="a",
                resource=_resource(),
                outcome=AuditOutcome.SUCCESS,
                **{field_name: "sensitive"},
            )


def test_result_count_is_count_not_data() -> None:
    """result_count is an integer (metadata), not a list or dict (the data itself)."""
    trail, sink = _trail()
    with trail.operation(action="a", actor=_actor(), resource=_resource()) as h:
        h.result_count = 99
    event = sink.events[0]
    assert isinstance(event.result_count, int)
    data = json.loads(event.model_dump_json(by_alias=True))
    assert data["resultCount"] == 99
    assert not isinstance(data["resultCount"], (list, dict))
