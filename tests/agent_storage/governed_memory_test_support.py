from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import (
    GovernedMemoryCreate,
    GovernedMemoryLifecycleMutation,
    GovernedMemoryManagementContext,
)
from agent_core.domain.governed_memory_operations import WorkerMemoryMutationPlan
from agent_core.domain.identifiers import MemoryId, SessionId, new_session_id
from agent_core.domain.leases import WorkerLease
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_storage import (
    PostgresEventStore,
    PostgresGovernedMemoryStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    bootstrap_control_plane_epoch,
)

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)
CURSOR_SIGNING_KEY = b"zebra-governed-memory-test-key-32"


@dataclass(frozen=True)
class MemoryEnvironment:
    dsn: str
    namespace: str
    session_id: SessionId
    lease: WorkerLease
    store: PostgresGovernedMemoryStore


def prepare_environment(dsn: str) -> MemoryEnvironment:
    namespace = f"memory-{uuid4()}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    session_id = new_session_id()
    created = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.USER,
        payload={"title": "Governed Memory"},
        created_at=NOW,
    )
    prepared = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.SYSTEM,
        payload={
            "title": "Governed Memory",
            "user_input": "Validate PostgreSQL Memory authority.",
            "workspace_root": "/tmp/governed-memory",
        },
        created_at=NOW,
    )
    PostgresEventStore(dsn, deployment_namespace=namespace).append(created)
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(
        rebuild_session([created])
    )
    lease = PostgresLeaseStore(dsn, deployment_namespace=namespace).acquire(
        session_id,
        owner_instance_id="memory-worker",
        ttl=timedelta(minutes=5),
    )
    PostgresWorkspaceProjectionStore(
        dsn,
        deployment_namespace=namespace,
    ).commit_worker_event(
        prepared,
        rebuild_session([created, prepared]),
        rebuild_workspace([created, prepared]),
        authority=WorkerMutationAuthority(
            deployment_namespace=namespace,
            session_id=session_id,
            lease_fence=lease.fence,
            expected_stream_revision=0,
        ),
    )
    return MemoryEnvironment(
        dsn=dsn,
        namespace=namespace,
        session_id=session_id,
        lease=lease,
        store=PostgresGovernedMemoryStore(
            dsn,
            deployment_namespace=namespace,
            cursor_signing_key=CURSOR_SIGNING_KEY,
        ),
    )


def candidate(
    environment: MemoryEnvironment,
    *,
    text: str,
    memory_id: MemoryId | None = None,
    memory_type: MemoryType = MemoryType.PREFERENCE,
    visibility: MemoryVisibility = MemoryVisibility.REPO,
    user_id: str | None = None,
    tenant_id: str | None = None,
    offset: int = 0,
) -> MemoryRecord:
    created_at = NOW + timedelta(seconds=offset)
    return MemoryRecord(
        memory_id=memory_id or MemoryId(uuid4()),
        memory_type=memory_type,
        text=text,
        confidence=0.9,
        status=MemoryStatus.CANDIDATE,
        visibility=visibility,
        repo_id="zebra-agent" if visibility is MemoryVisibility.REPO else None,
        user_id=user_id,
        tenant_id=tenant_id,
        source_session_id=environment.session_id,
        source_event_start=0,
        source_event_end=0,
        created_at=created_at,
        updated_at=created_at,
    )


def plan(
    environment: MemoryEnvironment,
    *,
    operation_id: str,
    expected_revision: int,
    records: tuple[MemoryRecord, ...],
    confirmed: tuple[MemoryId, ...] = (),
) -> WorkerMemoryMutationPlan:
    confirmations = frozenset(confirmed)
    creations = tuple(GovernedMemoryCreate.from_candidate(record) for record in records)
    mutations = tuple(
        GovernedMemoryLifecycleMutation(
            memory_id=record.memory_id,
            expected_revision=1,
            previous_status=MemoryStatus.CANDIDATE,
            status=MemoryStatus.CONFIRMED,
            updated_at=record.updated_at + timedelta(seconds=1),
        )
        for record in records
        if record.memory_id in confirmations
    )
    events: list[SessionEvent] = [
        candidate_event(record, sequence=expected_revision + index + 1)
        for index, record in enumerate(records)
    ]
    events.extend(
        review_event(
            record,
            previous_status=MemoryStatus.CANDIDATE,
            status=MemoryStatus.CONFIRMED,
            sequence=expected_revision + len(events) + 1,
            created_at=record.updated_at + timedelta(seconds=1),
        )
        for record in records
        if record.memory_id in confirmations
    )
    return WorkerMemoryMutationPlan.create(
        deployment_namespace=environment.namespace,
        operation_id=operation_id,
        session_id=environment.session_id,
        expected_stream_revision=expected_revision,
        creations=creations,
        lifecycle_mutations=mutations,
        events=tuple(events),
    )


def candidate_event(record: MemoryRecord, *, sequence: int) -> SessionEvent:
    assert record.source_session_id is not None
    assert record.source_event_start is not None
    assert record.source_event_end is not None
    return SessionEvent.create(
        session_id=record.source_session_id,
        sequence=sequence,
        event_type=EventType.MEMORY_CANDIDATE_EXTRACTED,
        actor=EventActor.HARNESS,
        payload={
            "memory_id": str(record.memory_id),
            "memory_type": record.memory_type.value,
            "status": record.status.value,
            "visibility": record.visibility.value,
            "text": record.text,
            "confidence": record.confidence,
            "source_event_start": record.source_event_start,
            "source_event_end": record.source_event_end,
            "repo_id": record.repo_id,
            "user_id": record.user_id,
            "tenant_id": record.tenant_id,
        },
        created_at=record.created_at,
    )


def review_event(
    record: MemoryRecord,
    *,
    previous_status: MemoryStatus,
    status: MemoryStatus,
    sequence: int,
    created_at: datetime,
) -> SessionEvent:
    assert record.source_session_id is not None
    return SessionEvent.create(
        session_id=record.source_session_id,
        sequence=sequence,
        event_type=EventType.MEMORY_REVIEW_RECORDED,
        actor=EventActor.HARNESS,
        payload={
            "memory_id": str(record.memory_id),
            "memory_type": record.memory_type.value,
            "previous_status": previous_status.value,
            "status": status.value,
            "operator": "system",
            "reason": "PostgreSQL governed Memory test",
            "superseded_memory_ids": [],
            "duplicate_of_memory_id": None,
        },
        created_at=created_at,
    )


def authority(
    environment: MemoryEnvironment,
    expected_revision: int,
) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace=environment.namespace,
        session_id=environment.session_id,
        lease_fence=environment.lease.fence,
        expected_stream_revision=expected_revision,
    )


def management(operation_id: str) -> GovernedMemoryManagementContext:
    return GovernedMemoryManagementContext(
        operation_id=operation_id,
        operator="memory-test",
        reason="validate governed Memory authority",
    )


def aggregate_state(environment: MemoryEnvironment) -> tuple[int, ...]:
    with psycopg.connect(environment.dsn) as connection:
        row = connection.execute(
            """
            WITH target(namespace, session_id) AS (VALUES (%s, %s))
            SELECT
                (SELECT count(*) FROM governed_memory_records r
                 WHERE r.deployment_namespace = target.namespace),
                (SELECT count(*) FROM governed_memory_operations o
                 WHERE o.deployment_namespace = target.namespace),
                (SELECT count(*) FROM session_events e
                 WHERE e.deployment_namespace = target.namespace
                   AND e.session_id = target.session_id),
                (SELECT current_version FROM session_streams s
                 WHERE s.deployment_namespace = target.namespace
                   AND s.session_id = target.session_id),
                (SELECT current_sequence FROM session_projections s
                 WHERE s.deployment_namespace = target.namespace
                   AND s.session_id = target.session_id),
                (SELECT current_sequence FROM workspace_projections w
                 WHERE w.deployment_namespace = target.namespace
                   AND w.session_id = target.session_id)
            FROM target
            """,
            (environment.namespace, environment.session_id),
        ).fetchone()
        assert row is not None
        return tuple(int(value) for value in row)
