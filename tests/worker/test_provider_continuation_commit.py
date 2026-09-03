from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_continuation import (
    CloudProviderContinuationArtifact,
    ProviderContinuationRef,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports import (
    CloudProviderContinuationCommitResult,
    LoadedCloudProviderContinuation,
    WorkerMutationAuthority,
)
from agent_core.ports.provider_continuation_cloud import (
    CloudProviderContinuationStorePort,
)
from zebra_agent_worker.execution import SessionExecutionService
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.provider_continuation_commit import (
    CloudProviderContinuationCoordinator,
)


class _FakeRecorder:
    def __init__(
        self,
        session: Session,
        workspace: WorkspaceProjection,
        authority: WorkerMutationAuthority,
    ) -> None:
        self.session = session
        self.workspace = workspace
        self.worker_mutation_authority = authority
        self.accepted: list[SessionEvent] = []

    def append_draft(self, draft: HarnessEventDraft) -> SessionEvent:
        raise AssertionError(f"unexpected local append: {draft.event_type}")

    def prepare(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
    ) -> SessionEvent:
        return SessionEvent.create(
            session_id=self.session.session_id,
            sequence=self.session.current_sequence + 1,
            event_type=event_type,
            actor=actor,
            payload=payload,
        )

    def accept_committed_aggregate(
        self,
        event: SessionEvent,
        *,
        session: Session,
        workspace: WorkspaceProjection,
    ) -> None:
        self.accepted.append(event)
        self.session = session
        self.workspace = workspace


class _FakeStore:
    def __init__(self, *, deployment_namespace: str) -> None:
        self.deployment_namespace = deployment_namespace
        self.commit_calls: list[dict[str, object]] = []
        self.load_calls: list[dict[str, object]] = []
        self.loaded: LoadedCloudProviderContinuation | None = None

    def commit_worker_selection(
        self,
        *,
        scope: OpaqueAuthorityScope,
        authority: WorkerMutationAuthority,
        continuation_id: str,
        session: Session,
        workspace: WorkspaceProjection,
        reference: ProviderContinuationRef,
        opaque_payload: bytes,
        maximum_ttl_seconds: int | None,
        selection_event: SessionEvent,
    ) -> CloudProviderContinuationCommitResult:
        kwargs: dict[str, object] = {
            "scope": scope,
            "authority": authority,
            "continuation_id": continuation_id,
            "session": session,
            "workspace": workspace,
            "reference": reference,
            "opaque_payload": opaque_payload,
            "maximum_ttl_seconds": maximum_ttl_seconds,
            "selection_event": selection_event,
        }
        self.commit_calls.append(kwargs)
        event = selection_event
        next_session = apply_session_event(session, event)
        next_workspace = apply_workspace_event(workspace, event)
        artifact = CloudProviderContinuationArtifact(
            continuation_id=continuation_id,
            scope=scope,
            deployment_namespace=self.deployment_namespace,
            session_id=session.session_id,
            reference=reference,
            payload_sha256=selection_event.payload["payload_sha256"],
            size_bytes=len(opaque_payload),
            lifecycle_revision=0,
            selection_event_id=event.event_id,
            selection_event_sequence=event.sequence,
            idempotency_key=event.idempotency_key or "missing",
            accepted_lease=authority.lease_fence,
        )
        self.loaded = LoadedCloudProviderContinuation(
            artifact=artifact,
            opaque_payload=opaque_payload,
        )
        return CloudProviderContinuationCommitResult(
            artifact=artifact,
            event=event,
            session=next_session,
            workspace=next_workspace,
        )

    def load_compatible(
        self,
        continuation_id: str,
        *,
        scope: OpaqueAuthorityScope,
        session_id: SessionId,
        provider: str,
        model_name: str,
        capability_version: str,
        as_of: datetime | None = None,
    ) -> LoadedCloudProviderContinuation | None:
        kwargs: dict[str, object] = {
            "scope": scope,
            "session_id": session_id,
            "provider": provider,
            "model_name": model_name,
            "capability_version": capability_version,
            "as_of": as_of,
        }
        self.load_calls.append({"continuation_id": continuation_id, **kwargs})
        return self.loaded

    def delete_for_worker(self, *args: Any, **kwargs: Any) -> object:  # pragma: no cover
        raise NotImplementedError

    def sweep_expired(self, *args: Any, **kwargs: Any) -> object:  # pragma: no cover
        raise NotImplementedError


def test_cloud_coordinator_stages_then_commits_one_fenced_aggregate() -> None:
    session, workspace = _bootstrap()
    scope = OpaqueAuthorityScope(
        authority_issuer="https://issuer.example",
        namespace_id="org-42",
        allowed_session_ids=(str(session.session_id),),
    )
    authority = _authority(session.session_id, expected_revision=session.current_sequence)
    recorder = _FakeRecorder(session, workspace, authority)
    store = _FakeStore(deployment_namespace="cloud-prod")
    coordinator = CloudProviderContinuationCoordinator(
        store=cast(CloudProviderContinuationStorePort, store),
        scope=scope,
        session_id=session.session_id,
    )
    reference = _reference()
    payload = b"opaque-provider-state"
    continuation_id = coordinator.prepare(reference, payload, 120)

    assert continuation_id is not None
    assert store.commit_calls == []

    event = coordinator.append_draft(
        _selection_draft(reference, continuation_id),
        cast(DurableHarnessEventRecorder, recorder),
    )

    assert len(store.commit_calls) == 1
    call = store.commit_calls[0]
    assert call["continuation_id"] == continuation_id
    assert call["opaque_payload"] == payload
    assert call["authority"] == authority
    assert event.idempotency_key == f"provider-continuation:{continuation_id}"
    assert event.payload["artifact_id"] == continuation_id
    assert event.payload["authority_issuer"] == scope.authority_issuer
    assert event.payload["namespace_id"] == scope.namespace_id
    assert recorder.accepted == [event]
    assert coordinator.recover([event]) == reference
    assert store.load_calls[0]["scope"] == scope

    with pytest.raises(ValueError, match="no staged payload"):
        coordinator.append_draft(
            _selection_draft(reference, continuation_id),
            cast(DurableHarnessEventRecorder, recorder),
        )


def test_cloud_coordinator_persists_capsule_fallback_without_artifact() -> None:
    class _FallbackRecorder(_FakeRecorder):
        def append_draft(self, draft: HarnessEventDraft) -> SessionEvent:
            return self.prepare(draft.event_type, draft.actor, draft.payload)

    session, workspace = _bootstrap()
    recorder = _FallbackRecorder(
        session,
        workspace,
        _authority(session.session_id, expected_revision=2),
    )
    coordinator = CloudProviderContinuationCoordinator(
        store=cast(
            CloudProviderContinuationStorePort,
            _FakeStore(deployment_namespace="cloud-prod"),
        ),
        scope=OpaqueAuthorityScope(
            authority_issuer="https://issuer.example",
            namespace_id="org-42",
            allowed_session_ids=(str(session.session_id),),
        ),
        session_id=session.session_id,
    )
    draft = HarnessEventDraft(
        event_type=EventType.CONTEXT_CONTINUATION_SELECTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "mode": "capsule_fallback", "reason": "provider unavailable"},
    )

    event = coordinator.append_draft(draft, cast(DurableHarnessEventRecorder, recorder))

    assert event.payload["mode"] == "capsule_fallback"


def test_cloud_provider_factory_rejects_implicit_sqlite_fallback(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicitly composed ControlPlaneStores"):
        SessionExecutionService(
            database_path=tmp_path / "sessions.sqlite",
            claim_service=cast(Any, object()),
            resume_service=cast(Any, object()),
            worker_projection_transaction=cast(Any, object()),
            deployment_namespace="cloud-prod",
            cloud_provider_continuation_factory=cast(Any, lambda _session_id: object()),
        )


def _bootstrap() -> tuple[Session, WorkspaceProjection]:
    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Provider continuation",
            user_input="continue",
            workspace_root=Path("/tmp/provider-continuation"),
            created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        )
    )
    return result.session, rebuild_workspace(list(result.events))


def _reference() -> ProviderContinuationRef:
    created_at = datetime(2026, 1, 1, 9, 1, tzinfo=UTC)
    return ProviderContinuationRef(
        reference_id="provider-ref-1",
        provider="provider-a",
        model_name="model-a",
        capability_version="1",
        source_hash="source-hash-1",
        created_at=created_at,
        expires_at=created_at + timedelta(minutes=5),
    )


def _selection_draft(reference: ProviderContinuationRef, continuation_id: str) -> HarnessEventDraft:
    return HarnessEventDraft(
        event_type=EventType.CONTEXT_CONTINUATION_SELECTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "mode": "provider_native",
            "reason": "provider compacted context",
            "reference_id": reference.reference_id,
            "provider": reference.provider,
            "model_name": reference.model_name,
            "capability_version": reference.capability_version,
            "source_hash": reference.source_hash,
            "artifact_id": continuation_id,
        },
    )


def _authority(session_id: SessionId, *, expected_revision: int) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace="cloud-prod",
        session_id=session_id,
        lease_fence=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=1,
            owner_instance_id="worker-1",
        ),
        expected_stream_revision=expected_revision,
    )
