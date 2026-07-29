from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectReceipt,
)
from agent_core.domain.cloud_artifact_requests import ArtifactFinalizeRequest
from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchStatus,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import (
    SessionId,
    new_artifact_id,
    new_session_id,
    new_tool_call_id,
)
from agent_core.domain.leases import LeaseFence
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports import WorkerMutationAuthority
from agent_tools.effect_guard_support import effect_identity
from zebra_agent_worker.cloud_effect_payloads import CloudEffectPayloadCoordinator
from zebra_agent_worker.tool_output_artifacts import (
    CloudToolOutputArtifactCoordinator,
    PreparedCloudArtifact,
)


class _Artifacts:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.staged: list[dict[str, Any]] = []
        self.pending: PreparedCloudArtifact | None = None
        self.released: list[str] = []

    def stage_bytes(self, **kwargs: Any) -> PreparedCloudArtifact:
        self.staged.append(kwargs)
        expectation = ArtifactObjectExpectation(
            deployment_namespace=kwargs["authority"].deployment_namespace,
            artifact_id=kwargs["artifact_id"],
            sha256=sha256(kwargs["payload"]).hexdigest(),
            size_bytes=len(kwargs["payload"]),
        )
        return PreparedCloudArtifact(
            artifact_id=kwargs["artifact_id"],
            session_id=kwargs["authority"].session_id,
            receipt=ArtifactObjectReceipt(
                expectation=expectation,
                object_version="version-1",
                verified_at=datetime.now(UTC),
            ),
            idempotency_scope=kwargs["idempotency_scope"],
            intended_event_sequence=kwargs["intended_event_sequence"],
        )

    def read_verified(self, artifact_id: object, *, namespace: str) -> bytes:
        del artifact_id, namespace
        return self.payload

    def stage_pending_output(
        self, artifact_uri: str, **kwargs: Any
    ) -> PreparedCloudArtifact | None:
        del artifact_uri, kwargs
        return self.pending

    def release_pending(self, artifact_uri: str) -> None:
        self.released.append(artifact_uri)


class _Dispatch:
    def __init__(self) -> None:
        self.schedule_request: EffectScheduleRequest | None = None
        self.schedule_finalize: ArtifactFinalizeRequest | None = None
        self.completed_finalize: ArtifactFinalizeRequest | None = None

    def schedule_with_payload(
        self,
        request: EffectScheduleRequest,
        *,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> EffectDispatch:
        del authority
        self.schedule_request = request
        self.schedule_finalize = artifact_finalize
        return EffectDispatch(
            dispatch_id=uuid4(),
            execution_session_id=request.execution_session_id,
            root_session_id=request.root_session_id,
            identity=request.identity,
            attempt=1,
            request_hash=request.request_hash,
            payload_artifact_ref=request.payload_artifact_ref,
            status=EffectDispatchStatus.PENDING,
            intent_event_id=request.started_event.event_id,
            created_at=request.started_event.created_at,
            updated_at=request.started_event.created_at,
        )

    def complete_with_payload(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> SessionEvent:
        del claim, result, authority
        self.completed_finalize = artifact_finalize
        return terminal_event

    def mark_uncertain_with_payload(
        self,
        claim: EffectClaim,
        *,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> SessionEvent:
        del claim, evidence, authority
        return terminal_event


def test_cloud_effect_request_uses_stable_artifact_and_payload_aware_schedule() -> None:
    session_id = new_session_id()
    call = _call()
    encoded = call.model_dump_json().encode()
    artifacts = _Artifacts(encoded)
    dispatch = _Dispatch()
    coordinator = CloudEffectPayloadCoordinator(
        session_id,
        cast(CloudToolOutputArtifactCoordinator, artifacts),
        cast(Any, dispatch),
    )
    authority = _authority(session_id)
    identity = effect_identity(call, "workspace-write")
    artifact_ref = coordinator.request_artifact_ref(
        root_session_id=session_id,
        identity=identity,
    )
    started = _event(session_id, 1, EventType.TOOL_EXECUTION_STARTED, artifact_ref)

    scheduled = coordinator.prepare_schedule(
        call,
        root_session_id=session_id,
        identity=identity,
        started_event=started,
        authority=authority,
    )

    same_effect_new_call = call.model_copy(update={"tool_call_id": new_tool_call_id()})
    assert coordinator.request_artifact_ref(
        root_session_id=session_id,
        identity=effect_identity(same_effect_new_call, "workspace-write"),
    ) == artifact_ref
    assert scheduled.payload_artifact_ref == artifact_ref
    assert artifacts.staged[0]["kind"] == "effect_tool_call"
    assert artifacts.staged[0]["allow_finalized_sequence_replay"] is True
    assert dispatch.schedule_finalize is not None
    assert dispatch.schedule_finalize.event_binding.event_id == started.event_id
    assert coordinator.read_tool_call(artifact_ref, namespace="cloud-test") == call


def test_cloud_effect_terminal_uses_atomic_payload_transition_only_for_pending_output() -> None:
    session_id = new_session_id()
    artifacts = _Artifacts(b"tool output")
    dispatch = _Dispatch()
    coordinator = CloudEffectPayloadCoordinator(
        session_id,
        cast(CloudToolOutputArtifactCoordinator, artifacts),
        cast(Any, dispatch),
    )
    authority = _authority(session_id)
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="artifact://output",
        metadata={"artifact_uri": "artifact://00000000-0000-0000-0000-000000000001"},
    )
    terminal = _event(session_id, 2, EventType.TOOL_EXECUTION_COMPLETED)

    assert coordinator.complete_with_payload(
        cast(EffectClaim, object()),
        result=result.model_copy(update={"metadata": {"artifact_uri": "https://external"}}),
        terminal_event=terminal,
        authority=authority,
    ) is None

    prepared = artifacts.stage_bytes(
        artifact_id=new_artifact_id(),
        payload=b"tool output",
        kind="tool_output",
        mime_type="text/plain",
        file_name="tool.txt",
        created_at=datetime.now(UTC),
        intended_event_sequence=2,
        authority=authority,
        idempotency_scope="tool-output",
    )
    artifacts.pending = prepared
    managed_result = result.model_copy(update={"metadata": {"artifact_uri": prepared.uri}})

    assert coordinator.complete_with_payload(
        cast(EffectClaim, object()),
        result=managed_result,
        terminal_event=terminal,
        authority=authority,
    ) == terminal
    assert dispatch.completed_finalize is not None
    assert dispatch.completed_finalize.event_binding.event_id == terminal.event_id
    assert artifacts.released == [prepared.uri]


def test_cloud_effect_terminal_rejects_unknown_managed_artifact() -> None:
    session_id = new_session_id()
    coordinator = CloudEffectPayloadCoordinator(
        session_id,
        cast(CloudToolOutputArtifactCoordinator, _Artifacts(b"missing")),
        cast(Any, _Dispatch()),
    )
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="managed output",
        metadata={"artifact_uri": f"artifact://{new_artifact_id()}"},
    )

    with pytest.raises(ValueError, match="no captured payload"):
        coordinator.complete_with_payload(
            cast(EffectClaim, object()),
            result=result,
            terminal_event=_event(session_id, 2, EventType.TOOL_EXECUTION_COMPLETED),
            authority=_authority(session_id),
        )


def _call() -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": "deploy"},
        created_at=datetime.now(UTC),
    )


def _authority(session_id: SessionId) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace="cloud-test",
        session_id=session_id,
        lease_fence=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=1,
            owner_instance_id="worker-a",
        ),
        expected_stream_revision=0,
    )


def _event(
    session_id: SessionId,
    sequence: int,
    event_type: EventType,
    artifact_uri: str | None = None,
) -> SessionEvent:
    payload: dict[str, object] = {
        "attempt_number": 1,
        "tool_name": "command.run",
        "tool_call_id": str(new_tool_call_id()),
    }
    if artifact_uri is not None:
        payload["metadata"] = {"artifact_uri": artifact_uri}
    if event_type is not EventType.TOOL_EXECUTION_STARTED:
        payload.update({"status": "executed", "output": "ok", "metadata": {}})
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        actor=EventActor.HARNESS,
        payload=payload,
    )
