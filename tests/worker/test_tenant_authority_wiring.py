"""Tenant-scoped attempt authority wiring for the default Cloud Worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import cast

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionError
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.sessions import Session, SessionStatus
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.runtime_authority import (
    TenantScopedAuthorityResolver,
    persist_attempt_authority,
)

NOW = datetime(2026, 8, 16, 16, 0, tzinfo=UTC)
ISSUER = "https://deployment-authority.example"


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[EventType, dict[str, object]]] = []

    def append(
        self,
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
        **_: object,
    ) -> None:
        assert actor is EventActor.SYSTEM
        self.events.append((event_type, payload))


def _resolver() -> TenantScopedAuthorityResolver:
    return TenantScopedAuthorityResolver(
        authority_issuer=ISSUER,
        policy_ref="policy/deployment-authority@1",
        policy_version="1",
        policy_effective_digest=sha256(b"deployment-authority").hexdigest(),
    )


def _scope(namespace_id: str) -> OpaqueAuthorityScope:
    return OpaqueAuthorityScope(authority_issuer=ISSUER, namespace_id=namespace_id)


def test_tenant_scoped_resolution_pins_the_session_namespace() -> None:
    recorder = _Recorder()
    resolver = _resolver()
    persisted = persist_attempt_authority(
        cast(DurableHarnessEventRecorder, recorder),
        resolver,
        _scope("tenant-a"),
        session_id=new_session_id(),
        existing_events=[],
        attempt_number=1,
        created_at=NOW,
    )
    assert persisted is True
    event_type, payload = recorder.events[0]
    assert event_type is EventType.EXECUTION_AUTHORITY_RESOLVED
    assert payload["namespace_id"] == "tenant-a"
    assert payload["authority_issuer"] == ISSUER


def test_tenant_scoped_revalidation_reuses_the_same_namespace() -> None:
    recorder = _Recorder()
    resolver = _resolver()
    session_id = new_session_id()
    assert (
        persist_attempt_authority(
            cast(DurableHarnessEventRecorder, recorder),
            resolver,
            _scope("tenant-b"),
            session_id=session_id,
            existing_events=[],
            attempt_number=1,
            created_at=NOW,
        )
        is True
    )
    resolved = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
        actor=EventActor.SYSTEM,
        payload=recorder.events[0][1],
        created_at=NOW,
    )
    persisted = persist_attempt_authority(
        cast(DurableHarnessEventRecorder, recorder),
        resolver,
        _scope("tenant-b"),
        session_id=session_id,
        existing_events=[resolved],
        attempt_number=1,
        created_at=NOW + timedelta(seconds=10),
    )
    assert persisted is True
    assert recorder.events[-1][0] is EventType.EXECUTION_AUTHORITY_REVALIDATED
    assert recorder.events[-1][1]["prior_snapshot_digest"] == recorder.events[0][1][
        "snapshot_digest"
    ]


def test_foreign_issuer_scope_fails_closed() -> None:
    recorder = _Recorder()
    resolver = _resolver()
    with pytest.raises(ExecutionAuthorityResolutionError):
        persist_attempt_authority(
            cast(DurableHarnessEventRecorder, recorder),
            resolver,
            OpaqueAuthorityScope(
                authority_issuer="https://other-issuer.example",
                namespace_id="tenant-a",
            ),
            session_id=new_session_id(),
            existing_events=[],
            attempt_number=1,
            created_at=NOW,
        )


def test_cloud_composition_builds_the_tenant_scope_provider() -> None:
    from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
    from agent_storage.runtime_composition import CloudCompositionSettings
    from zebra_agent_worker.cloud_composition import compose_cloud_worker

    class _MemoryObjects:
        def put_if_absent(self, request: object) -> object:
            return None

        def verify(self, expectation: object) -> object:
            return None

        def read_verified(self, expectation: object) -> bytes:
            return b""

        def read_version_verified(self, expectation: object, version: str) -> bytes:
            return b""

        def delete_if_version(self, expectation: object, version: str) -> object:
            return None

    cloud = CloudCompositionSettings(
        dsn="postgresql://unit",
        deployment_namespace="deployment-a",
        memory_cursor_signing_key=b"unit-signing-key-32-bytes-XXXXXXXX",
        artifact_objects=cast(ArtifactObjectStorePort, _MemoryObjects()),
        history_scope=OpaqueAuthorityScope(
            authority_issuer=ISSUER, namespace_id="history"
        ),
        continuation_scope=OpaqueAuthorityScope(
            authority_issuer=ISSUER, namespace_id="continuation"
        ),
    )
    composition = compose_cloud_worker(cloud)
    assert composition.authority_resolver is not None
    assert composition.authority_scope_provider is not None

    tenant_session = Session(
        session_id=new_session_id(),
        title="tenant session",
        status=SessionStatus.READY,
        created_at=NOW,
        updated_at=NOW,
        current_sequence=1,
        namespace_id="tenant-9",
    )
    scope = composition.authority_scope_provider(tenant_session)
    assert isinstance(scope, OpaqueAuthorityScope)
    assert scope.namespace_id == "tenant-9"
    assert scope.authority_issuer == ISSUER

    operator_session = Session(
        session_id=new_session_id(),
        title="operator session",
        status=SessionStatus.READY,
        created_at=NOW,
        updated_at=NOW,
        current_sequence=1,
    )
    fallback_scope = composition.authority_scope_provider(operator_session)
    assert isinstance(fallback_scope, OpaqueAuthorityScope)
    assert fallback_scope.namespace_id == "deployment-a"
