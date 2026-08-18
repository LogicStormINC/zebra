from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchStatus,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import (
    EventId,
    SessionId,
    new_event_id,
    new_session_id,
    new_tool_call_id,
)
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.ports import EffectDispatchPort
from pydantic import ValidationError

NOW = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
REQUEST_HASH = "a" * 64


def _identity() -> EffectIdentity:
    return EffectIdentity(
        authority_scope_hash="authority",
        tool_name="files.patch",
        operation_kind="apply_patch",
        target_hash="target",
        canonical_effect_hash="effect",
    )


def _event(session_id: SessionId) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=3,
        event_type=EventType.TOOL_EXECUTION_STARTED,
        actor=EventActor.TOOL,
        created_at=NOW,
    )


def _result() -> ToolResult:
    return ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="ok",
    )


def test_succeeded_dispatch_rejects_failed_tool_result() -> None:
    failed = _result().model_copy(update={"status": ToolCallStatus.FAILED})

    with pytest.raises(ValidationError, match="must be executed"):
        _dispatch(
            EffectDispatchStatus.SUCCEEDED,
            terminal_event_id=new_event_id(),
            result=failed,
        )


def _dispatch(
    status: EffectDispatchStatus,
    *,
    terminal_event_id: EventId | None = None,
    result: ToolResult | None = None,
    evidence: EffectEvidence | None = None,
    evidence_history: tuple[EffectEvidence, ...] = (),
    updated_at: datetime = NOW,
) -> EffectDispatch:
    session_id = new_session_id()
    return EffectDispatch(
        dispatch_id=uuid4(),
        execution_session_id=session_id,
        root_session_id=session_id,
        identity=_identity(),
        attempt=1,
        request_hash=REQUEST_HASH,
        payload_artifact_ref="artifact://effect/request",
        status=status,
        intent_event_id=new_event_id(),
        terminal_event_id=terminal_event_id,
        result=result,
        evidence=evidence,
        evidence_history=evidence_history,
        created_at=NOW,
        updated_at=updated_at,
    )


def test_schedule_request_preserves_execution_and_root_session_scopes() -> None:
    root_session_id = new_session_id()
    execution_session_id = new_session_id()
    request = EffectScheduleRequest(
        root_session_id=root_session_id,
        identity=_identity(),
        request_hash=REQUEST_HASH.upper(),
        payload_artifact_ref=" artifact://effect/request ",
        started_event=_event(execution_session_id),
    )

    assert request.execution_session_id == execution_session_id
    assert request.root_session_id == root_session_id
    assert request.request_hash == REQUEST_HASH
    assert request.payload_artifact_ref == "artifact://effect/request"
    assert request.ledger_key == request.identity.ledger_key()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("request_hash", "not-sha256", "sha256"),
        ("payload_artifact_ref", " ", "must not be blank"),
    ],
)
def test_schedule_request_rejects_invalid_persistence_keys(
    field: str, value: str, message: str
) -> None:
    values = {
        "root_session_id": new_session_id(),
        "identity": _identity(),
        "request_hash": REQUEST_HASH,
        "payload_artifact_ref": "artifact://effect/request",
        "started_event": _event(new_session_id()),
        field: value,
    }

    with pytest.raises(ValidationError, match=message):
        EffectScheduleRequest.model_validate(values)


def test_schedule_request_requires_started_event() -> None:
    completed_event = _event(new_session_id()).model_copy(
        update={"event_type": EventType.TOOL_EXECUTION_COMPLETED}
    )
    with pytest.raises(ValidationError, match="TOOL_EXECUTION_STARTED"):
        EffectScheduleRequest(
            root_session_id=new_session_id(),
            identity=_identity(),
            request_hash=REQUEST_HASH,
            payload_artifact_ref="artifact://effect/request",
            started_event=completed_event,
        )


def test_dispatch_accepts_reconciled_uncertain_without_terminal_event() -> None:
    evidence = EffectEvidence(reason_code="claim_expired")
    dispatch = _dispatch(
        EffectDispatchStatus.UNCERTAIN,
        evidence=evidence,
        evidence_history=(evidence,),
    )

    assert dispatch.terminal_event_id is None
    assert dispatch.status is EffectDispatchStatus.UNCERTAIN


def test_dispatch_rejects_evidence_history_with_different_latest_value() -> None:
    with pytest.raises(ValidationError, match="must end the evidence history"):
        _dispatch(
            EffectDispatchStatus.UNCERTAIN,
            evidence=EffectEvidence(reason_code="resolution"),
            evidence_history=(EffectEvidence(reason_code="claim_expired"),),
        )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"provider_operation_id_hash": "provider-id"}, "sha256"),
        ({"detail": "x" * 1025}, "at most 1024"),
    ],
)
def test_effect_evidence_is_bounded_and_hash_only(
    values: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        EffectEvidence(reason_code="provider_failure", **values)


def test_dispatch_accepts_provider_uncertain_with_terminal_event() -> None:
    terminal_event_id = new_event_id()
    dispatch = _dispatch(
        EffectDispatchStatus.UNCERTAIN,
        terminal_event_id=terminal_event_id,
        evidence=EffectEvidence(reason_code="provider_timeout"),
    )

    assert dispatch.terminal_event_id == terminal_event_id


@pytest.mark.parametrize(
    "status",
    [
        EffectDispatchStatus.SUCCEEDED,
        EffectDispatchStatus.FAILED_NO_EFFECT,
        EffectDispatchStatus.DEAD_LETTER,
    ],
)
def test_terminal_status_requires_terminal_event(status: EffectDispatchStatus) -> None:
    if status is EffectDispatchStatus.SUCCEEDED:
        with pytest.raises(ValidationError, match="requires terminal_event_id"):
            _dispatch(status, result=_result())
    else:
        with pytest.raises(ValidationError, match="requires terminal_event_id"):
            _dispatch(status, evidence=EffectEvidence(reason_code="terminal"))


@pytest.mark.parametrize("status", [EffectDispatchStatus.PENDING, EffectDispatchStatus.CLAIMED])
def test_non_terminal_status_rejects_terminal_event(status: EffectDispatchStatus) -> None:
    with pytest.raises(ValidationError, match="cannot carry terminal_event_id"):
        _dispatch(status, terminal_event_id=new_event_id())


@pytest.mark.parametrize(
    "status",
    [
        EffectDispatchStatus.FAILED_NO_EFFECT,
        EffectDispatchStatus.UNCERTAIN,
        EffectDispatchStatus.DEAD_LETTER,
    ],
)
def test_failure_and_uncertain_statuses_require_evidence(
    status: EffectDispatchStatus,
) -> None:
    terminal_event_id = None if status is EffectDispatchStatus.UNCERTAIN else new_event_id()
    with pytest.raises(ValidationError, match="require evidence"):
        _dispatch(status, terminal_event_id=terminal_event_id)


def test_only_succeeded_dispatch_carries_result() -> None:
    succeeded = _dispatch(
        EffectDispatchStatus.SUCCEEDED,
        terminal_event_id=new_event_id(),
        result=_result(),
    )
    assert succeeded.result is not None

    with pytest.raises(ValidationError, match="only succeeded"):
        _dispatch(EffectDispatchStatus.PENDING, result=_result())


def test_dispatch_rejects_invalid_hash_artifact_and_timestamp_order() -> None:
    values = _dispatch(EffectDispatchStatus.PENDING).model_dump()
    with pytest.raises(ValidationError, match="sha256"):
        EffectDispatch.model_validate({**values, "request_hash": "bad"})
    with pytest.raises(ValidationError, match="must not be blank"):
        EffectDispatch.model_validate({**values, "payload_artifact_ref": " "})
    with pytest.raises(ValidationError, match="must not precede"):
        _dispatch(
            EffectDispatchStatus.PENDING,
            updated_at=NOW - timedelta(seconds=1),
        )


def test_effect_claim_requires_claimed_dispatch_and_future_expiry() -> None:
    fence = LeaseFence(
        control_plane_epoch=uuid4(),
        fencing_token=7,
        owner_instance_id="worker-1",
    )
    claim = EffectClaim(
        dispatch=_dispatch(EffectDispatchStatus.CLAIMED),
        claim_fence=fence,
        claim_expires_at=NOW + timedelta(seconds=30),
    )
    assert claim.claim_fence == fence

    with pytest.raises(ValidationError, match="requires a claimed dispatch"):
        EffectClaim(
            dispatch=_dispatch(EffectDispatchStatus.PENDING),
            claim_fence=fence,
            claim_expires_at=NOW + timedelta(seconds=30),
        )
    with pytest.raises(ValidationError, match="expiry must follow"):
        EffectClaim(
            dispatch=_dispatch(EffectDispatchStatus.CLAIMED),
            claim_fence=fence,
            claim_expires_at=NOW,
        )


def test_effect_dispatch_port_is_exported() -> None:
    assert EffectDispatchPort.__name__ == "EffectDispatchPort"
