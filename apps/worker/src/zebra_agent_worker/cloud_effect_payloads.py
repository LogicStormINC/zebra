"""Cloud Artifact coordination for fenced Effect request and result payloads."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Protocol, cast
from uuid import UUID, uuid5

from agent_core.domain.cloud_artifact_requests import ArtifactFinalizeRequest
from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.ports import EffectDispatchPort, WorkerMutationAuthority

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.tool_output_artifacts import (
    CloudToolOutputArtifactCoordinator,
    PreparedCloudArtifact,
)


class PayloadAwareEffectDispatch(Protocol):
    def schedule_with_payload(
        self,
        request: EffectScheduleRequest,
        *,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> EffectDispatch: ...

    def complete_with_payload(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> SessionEvent: ...

    def mark_uncertain_with_payload(
        self,
        claim: EffectClaim,
        *,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> SessionEvent: ...


class CloudEffectPayloadCoordinator:
    """Stage object bytes, then delegate the relational atomic boundary to PostgreSQL."""

    def __init__(
        self,
        session_id: SessionId,
        artifacts: CloudToolOutputArtifactCoordinator,
        dispatch: PayloadAwareEffectDispatch,
    ) -> None:
        self._session_id = session_id
        self._artifacts = artifacts
        self._dispatch = dispatch

    def request_artifact_ref(
        self,
        *,
        root_session_id: SessionId,
        identity: EffectIdentity,
    ) -> str:
        return f"artifact://{_request_artifact_id(root_session_id, identity)}"

    def prepare_schedule(
        self,
        tool_call: ToolCall,
        *,
        root_session_id: SessionId,
        identity: EffectIdentity,
        started_event: SessionEvent,
        authority: WorkerMutationAuthority,
    ) -> EffectDispatch:
        artifact_id = _request_artifact_id(root_session_id, identity)
        prepared = self._artifacts.stage_bytes(
            artifact_id=artifact_id,
            payload=tool_call.model_dump_json().encode(),
            kind="effect_tool_call",
            mime_type="application/json",
            file_name="tool-call.json",
            created_at=tool_call.created_at,
            intended_event_sequence=started_event.sequence,
            authority=authority,
            idempotency_scope="effect-request",
            allow_finalized_sequence_replay=True,
        )
        return self._dispatch.schedule_with_payload(
            EffectScheduleRequest(
                root_session_id=root_session_id,
                identity=identity,
                request_hash=identity.canonical_effect_hash,
                payload_artifact_ref=prepared.uri,
                started_event=started_event,
            ),
            authority=authority,
            artifact_finalize=prepared.finalize_request(started_event),
        )

    def read_tool_call(self, artifact_ref: str, *, namespace: str) -> ToolCall:
        artifact_id = _artifact_id(artifact_ref)
        return ToolCall.model_validate_json(
            self._artifacts.read_verified(artifact_id, namespace=namespace)
        )

    def complete_with_payload(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
    ) -> SessionEvent | None:
        prepared = self._stage_terminal(result, terminal_event, authority)
        if prepared is None:
            return None
        persisted = self._dispatch.complete_with_payload(
            claim,
            result=result,
            terminal_event=terminal_event,
            authority=authority,
            artifact_finalize=prepared.finalize_request(terminal_event),
        )
        self._artifacts.release_pending(prepared.uri)
        return persisted

    def mark_uncertain_with_payload(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
    ) -> SessionEvent | None:
        prepared = self._stage_terminal(result, terminal_event, authority)
        if prepared is None:
            return None
        persisted = self._dispatch.mark_uncertain_with_payload(
            claim,
            evidence=evidence,
            terminal_event=terminal_event,
            authority=authority,
            artifact_finalize=prepared.finalize_request(terminal_event),
        )
        self._artifacts.release_pending(prepared.uri)
        return persisted

    def _stage_terminal(
        self,
        result: ToolResult,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
    ) -> PreparedCloudArtifact | None:
        artifact_uri = result.metadata.get("artifact_uri")
        if not isinstance(artifact_uri, str):
            return None
        prepared = self._artifacts.stage_pending_output(
            artifact_uri,
            intended_event_sequence=terminal_event.sequence,
            authority=authority,
        )
        if prepared is None and artifact_uri.startswith("artifact://"):
            raise ValueError("managed Effect result Artifact has no captured payload")
        return prepared


def build_cloud_effect_payloads(
    session_id: SessionId,
    artifacts: CloudToolOutputArtifactCoordinator | None,
    dispatch: EffectDispatchPort | None,
) -> CloudEffectPayloadCoordinator | None:
    if artifacts is None or dispatch is None:
        return None
    return CloudEffectPayloadCoordinator(
        session_id,
        artifacts,
        cast(PayloadAwareEffectDispatch, dispatch),
    )


def require_effect_authority(
    recorders: list[DurableHarnessEventRecorder],
) -> WorkerMutationAuthority:
    if not recorders:
        raise RuntimeError("Effect recorder is not initialized")
    authority = recorders[-1].worker_mutation_authority
    if authority is None:
        raise RuntimeError("cloud Effect payload authority is unavailable")
    return authority


def effect_authority_provider(
    recorders: list[DurableHarnessEventRecorder],
    *,
    enabled: bool,
) -> Callable[[], WorkerMutationAuthority] | None:
    return partial(require_effect_authority, recorders) if enabled else None


def _request_artifact_id(
    root_session_id: SessionId,
    identity: EffectIdentity,
) -> ArtifactId:
    return ArtifactId(uuid5(UUID(str(root_session_id)), f"effect-request:{identity.ledger_key()}"))


def _artifact_id(artifact_ref: str) -> ArtifactId:
    prefix = "artifact://"
    if not artifact_ref.startswith(prefix):
        raise ValueError("Effect payload is not a governed Artifact")
    try:
        return ArtifactId(UUID(artifact_ref.removeprefix(prefix)))
    except ValueError as error:
        raise ValueError("Effect payload Artifact id is invalid") from error
