from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionRequest,
    ExecutionAuthorityRevalidation,
    ExecutionAuthorityRevalidationRequest,
    ExecutionAuthoritySnapshot,
)
from agent_core.domain.identifiers import new_session_id
from agent_core.ports.execution_authority import ExecutionAuthorityResolverPort
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.runtime_authority import (
    FailClosedExternalAuthorityResolver,
    TrustedLocalExecutionAuthorityResolver,
    persist_attempt_authority,
)

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[EventType, dict[str, object]]] = []

    def append(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        **_: object,
    ) -> None:
        assert actor is EventActor.SYSTEM
        self.calls.append((event_type, payload))


class _NarrowingResolver:
    def __init__(self) -> None:
        self.base = TrustedLocalExecutionAuthorityResolver(
            authority_issuer="local://trusted",
            namespace_id="local-scope",
            policy_ref="policy/local@1",
            policy_version="1",
            policy_effective_digest="b" * 64,
            granted_authorities=("agent.execute", "agent.read"),
        )
        self.revalidation_count = 0

    def resolve_for_attempt(
        self,
        request: ExecutionAuthorityResolutionRequest,
    ) -> ExecutionAuthoritySnapshot:
        return self.base.resolve_for_attempt(request)

    def revalidate_attempt(
        self,
        request: ExecutionAuthorityRevalidationRequest,
    ) -> ExecutionAuthorityRevalidation:
        self.revalidation_count += 1
        if self.revalidation_count == 1:
            request = request.model_copy(update={"capability_ceiling": ("agent.execute",)})
        return self.base.revalidate_attempt(request)


def _resolver() -> TrustedLocalExecutionAuthorityResolver:
    return TrustedLocalExecutionAuthorityResolver(
        authority_issuer="local://trusted",
        namespace_id="local-scope",
        policy_ref="policy/local@1",
        policy_version="1",
        policy_effective_digest="b" * 64,
    )


def test_worker_persists_resolution_before_attempt_and_revalidates_same_attempt() -> None:
    session_id = new_session_id()
    scope = OpaqueAuthorityScope(
        authority_issuer="local://trusted",
        namespace_id="local-scope",
    )
    recorder = _Recorder()
    resolver = _resolver()
    recorder_like = cast(DurableHarnessEventRecorder, recorder)
    first = persist_attempt_authority(
        recorder_like,
        resolver,
        scope,
        session_id=session_id,
        existing_events=[],
        attempt_number=1,
        created_at=NOW,
    )
    assert first is True
    assert recorder.calls[0][0] is EventType.EXECUTION_AUTHORITY_RESOLVED
    resolved = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
        actor=EventActor.SYSTEM,
        payload=recorder.calls[0][1],
        created_at=NOW,
    )
    second = persist_attempt_authority(
        recorder_like,
        resolver,
        scope,
        session_id=session_id,
        existing_events=[resolved],
        attempt_number=1,
        created_at=NOW + timedelta(minutes=1),
    )
    assert second is True
    assert recorder.calls[1][0] is EventType.EXECUTION_AUTHORITY_REVALIDATED
    assert "effective_snapshot" in recorder.calls[1][1]


def test_revalidation_replay_uses_latest_effective_snapshot_and_fails_closed_on_expansion() -> None:
    session_id = new_session_id()
    scope = OpaqueAuthorityScope(
        authority_issuer="local://trusted",
        namespace_id="local-scope",
    )
    recorder = _Recorder()
    resolver = _NarrowingResolver()
    recorder_like = cast(DurableHarnessEventRecorder, recorder)

    persist_attempt_authority(
        recorder_like,
        resolver,
        scope,
        session_id=session_id,
        existing_events=[],
        attempt_number=1,
        created_at=NOW,
    )
    resolved = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
        actor=EventActor.SYSTEM,
        payload=recorder.calls[0][1],
        created_at=NOW,
    )
    persist_attempt_authority(
        recorder_like,
        resolver,
        scope,
        session_id=session_id,
        existing_events=[resolved],
        attempt_number=1,
        created_at=NOW + timedelta(minutes=1),
    )
    revalidated = SessionEvent.create(
        session_id=session_id,
        sequence=2,
        event_type=EventType.EXECUTION_AUTHORITY_REVALIDATED,
        actor=EventActor.SYSTEM,
        payload=recorder.calls[1][1],
        created_at=NOW + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="expanded capabilities"):
        persist_attempt_authority(
            recorder_like,
            resolver,
            scope,
            session_id=session_id,
            existing_events=[resolved, revalidated],
            attempt_number=1,
            created_at=NOW + timedelta(minutes=2),
        )


def test_external_authority_fails_closed_without_verifier() -> None:
    resolver: ExecutionAuthorityResolverPort = FailClosedExternalAuthorityResolver()
    request = ExecutionAuthorityResolutionRequest(
        session_id=new_session_id(),
        attempt_number=1,
        scope=OpaqueAuthorityScope(
            authority_issuer="https://business.example.com",
            namespace_id="scope-a",
        ),
        validated_at=NOW,
    )
    with pytest.raises(ValueError, match="verifier is not configured"):
        resolver.resolve_for_attempt(request)
