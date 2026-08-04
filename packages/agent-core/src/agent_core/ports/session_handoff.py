import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import (
    DEFAULT_MAX_HANDOFF_STAGE,
    HandoffActorKind,
    HandoffOperationStatus,
    HandoffReason,
    SessionHandoffEnvelope,
    SessionLineage,
    WorkspaceBindingRevision,
)
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS
from agent_core.ports.handoff_dispatch_store import HandoffDispatch


@dataclass(frozen=True, slots=True)
class HandoffSourceFacts:
    stream_version: int
    lease_fence: LeaseFence | None
    has_active_lease: bool
    authority_revision: str
    workspace_revision: WorkspaceBindingRevision
    task_profile_revision: str
    effective_depth_limit: int = DEFAULT_MAX_HANDOFF_STAGE


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


def canonical_handoff_request_hash(
    request: SessionHandoffCreateRequest,
    *,
    objective: str,
    completed_work: tuple[str, ...],
    pending_work: tuple[str, ...],
) -> str:
    """Bind reservation idempotency to every input later persisted by commit."""
    encoded = json.dumps(
        {
            "source_session_id": str(request.source_session_id),
            "title": request.title,
            "reason": request.reason.value,
            "stage_prompt": request.stage_prompt,
            "focus": request.focus,
            "principal_identity_hash": request.principal_identity_hash,
            "actor_kind": request.actor_kind.value,
            "requested_authority": sorted(request.requested_authority),
            "objective": objective,
            "completed_work": completed_work,
            "pending_work": pending_work,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


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
    source_lease_fence: LeaseFence | None
    authority_revision: str
    workspace_revision: WorkspaceBindingRevision
    task_profile_revision: str
    effective_depth_limit: int
    artifact_id: str | None
    created_at: datetime
    updated_at: datetime
    abort_code: str | None = None


@dataclass(frozen=True, slots=True)
class SessionHandoffAbortRequest:
    """Administrative CAS evidence for aborting one reserved Handoff."""

    operation: HandoffOperation
    authority: AdministrativeMutationCAS
    code: str


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
    def inspect_source_facts(
        self,
        session_id: SessionId,
        *,
        at: datetime,
    ) -> HandoffSourceFacts: ...

    def reserve(
        self,
        request: SessionHandoffCreateRequest,
        *,
        request_hash: str,
        expected_source_stream_version: int,
        source_lease_fence: LeaseFence | None,
        authority_revision: str,
        workspace_revision: WorkspaceBindingRevision,
        task_profile_revision: str,
        effective_depth_limit: int,
    ) -> HandoffOperation: ...

    def commit(self, request: SessionHandoffCommitRequest) -> SessionHandoffResult: ...

    def abort(self, operation_id: str, *, code: str) -> HandoffOperation: ...

    def get_handoff(self, handoff_id: HandoffId) -> SessionHandoffResult | None: ...

    def get_envelope(self, handoff_id: HandoffId) -> SessionHandoffEnvelope | None: ...

    def get_lineage(self, session_id: SessionId) -> tuple[SessionLineage, ...]: ...

    def rebuild_lineage_index(self) -> int: ...

    def abort_stale_preparing(self, *, before: datetime) -> int: ...

    def claim_dispatch(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_seconds: int = 60,
    ) -> HandoffDispatch | None: ...

    def acknowledge_dispatch(self, delivery_id: str, *, worker_id: str) -> None: ...


class SessionHandoffAbortPort(Protocol):
    """Stronger cloud-only abort seam; local SQLite keeps its legacy Port."""

    def abort_authorized(self, request: SessionHandoffAbortRequest) -> HandoffOperation: ...
