from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.session_handoff import (
    HandoffActorKind,
    HandoffOperationStatus,
    HandoffReason,
    SessionHandoffEnvelope,
    SessionLineage,
    WorkspaceBindingRevision,
)


@dataclass(frozen=True, slots=True)
class SessionHandoffCreateRequest:
    source_session_id: SessionId
    idempotency_key: str
    title: str
    reason: HandoffReason
    stage_prompt: str
    principal_identity_hash: str
    actor_kind: HandoffActorKind
    focus: str | None = None
    requested_authority: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class HandoffOperation:
    operation_id: str
    status: HandoffOperationStatus
    source_session_id: SessionId
    target_session_id: SessionId
    handoff_id: HandoffId
    idempotency_key_hash: str
    request_hash: str
    expected_source_stream_version: int
    source_lease_fencing_token: int | None
    authority_revision: str
    workspace_revision: WorkspaceBindingRevision
    task_profile_revision: str
    effective_depth_limit: int
    artifact_id: str | None
    created_at: datetime
    updated_at: datetime
    abort_code: str | None = None


@dataclass(frozen=True, slots=True)
class SessionHandoffCommitRequest:
    operation: HandoffOperation
    create_request: SessionHandoffCreateRequest
    envelope: SessionHandoffEnvelope
    artifact_id: str
    source_policy_profile: str | None = None
    source_tool_profile: str | None = None
    source_network_profile: str | None = None
    source_network_allowlist: tuple[str, ...] = ()
    source_mcp_allowlist: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SessionHandoffResult:
    handoff_id: HandoffId
    source_session_id: SessionId
    child_session_id: SessionId
    lineage: SessionLineage
    artifact_id: str
    checksum: str
    child_status: str
    idempotent_replay: bool = False


class SessionHandoffPort(Protocol):
    def reserve(
        self,
        request: SessionHandoffCreateRequest,
        *,
        request_hash: str,
        expected_source_stream_version: int,
        source_lease_fencing_token: int | None,
        authority_revision: str,
        workspace_revision: WorkspaceBindingRevision,
        task_profile_revision: str,
        effective_depth_limit: int,
    ) -> HandoffOperation: ...

    def commit(self, request: SessionHandoffCommitRequest) -> SessionHandoffResult: ...

    def abort(self, operation_id: str, *, code: str) -> HandoffOperation: ...

    def get_handoff(self, handoff_id: HandoffId) -> SessionHandoffResult | None: ...

    def get_lineage(self, session_id: SessionId) -> tuple[SessionLineage, ...]: ...
