from __future__ import annotations

import os
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryCreate,
    GovernedMemoryLifecycleMutation,
    GovernedMemoryManagementContext,
    GovernedMemoryTombstone,
)
from agent_core.domain.governed_memory_operations import WorkerMemoryMutationPlan
from agent_core.domain.identifiers import MemoryId, SessionId, new_session_id
from agent_core.domain.leases import LeaseLostError, WorkerLease
from agent_core.domain.memories import (
    MemoryQuery,
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
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.governed_memory_rows import provenance_digest
from psycopg import sql
from psycopg.conninfo import make_conninfo

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)
CURSOR_SIGNING_KEY = b"zebra-governed-memory-test-key-32"


@dataclass(frozen=True)
class _MemoryEnvironment:
    dsn: str
    namespace: str
    session_id: SessionId
    lease: WorkerLease
    store: PostgresGovernedMemoryStore


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"governed_memory_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def memory_environment(dsn: str) -> _MemoryEnvironment:
    return _prepare_environment(dsn)


def test_governed_memory_provenance_digest_is_stable_and_content_free() -> None:
    record = MemoryRecord(
        memory_id=MemoryId(UUID("00000000-0000-0000-0000-000000000001")),
        memory_type=MemoryType.PROCEDURE,
        text="Run make test.",
        confidence=0.9,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        source_session_id=SessionId(UUID("00000000-0000-0000-0000-000000000002")),
        source_event_start=3,
        source_event_end=5,
        source_commit_sha="abc123",
        created_at=NOW,
        updated_at=NOW,
    )

    assert provenance_digest(record) == (
        "c8cc634b6e9d9d57565cc236def131d41577709f633c77f1e04048ee7998d1d2"
    )
    assert provenance_digest(record.model_copy(update={"text": "Never persisted in digest"})) == (
        provenance_digest(record)
    )


def test_regenerated_creation_is_promoted_under_canonical_memory_id(
    memory_environment: _MemoryEnvironment,
) -> None:
    original = _candidate(memory_environment, text="Use the canonical Memory ID.")
    first_plan = _plan(
        memory_environment,
        operation_id="memory:create-canonical",
        expected_revision=1,
        records=(original,),
    )
    memory_environment.store.commit_worker_candidates(
        first_plan,
        authority=_authority(memory_environment, 1),
    )
    regenerated = original.model_copy(
        update={
            "memory_id": MemoryId(uuid4()),
            "created_at": NOW + timedelta(minutes=1),
            "updated_at": NOW + timedelta(minutes=1),
        }
    )
    promotion = _plan(
        memory_environment,
        operation_id="memory:promote-regenerated",
        expected_revision=2,
        records=(regenerated,),
        confirmed=(regenerated.memory_id,),
    )

    committed = memory_environment.store.commit_worker_candidates(
        promotion,
        authority=_authority(memory_environment, 2),
    )

    assert committed.receipt.memories == (
        committed.receipt.memories[0].model_copy(
            update={
                "memory_id": original.memory_id,
                "revision": 2,
                "status": MemoryStatus.CONFIRMED,
            }
        ),
    )
    assert memory_environment.store.get(regenerated.memory_id) is None
    assert memory_environment.store.get(original.memory_id).status is MemoryStatus.CONFIRMED  # type: ignore[union-attr]
    with psycopg.connect(memory_environment.dsn) as connection:
        assert connection.execute(
            """SELECT count(*) FROM governed_memory_records
            WHERE deployment_namespace = %s""",
            (memory_environment.namespace,),
        ).fetchone() == (1,)
    events = PostgresEventStore(
        memory_environment.dsn,
        deployment_namespace=memory_environment.namespace,
    ).list_for_session(memory_environment.session_id)
    assert [event.payload["memory_id"] for event in events[-2:]] == [
        str(original.memory_id),
        str(original.memory_id),
    ]


def test_delete_retains_content_free_tombstone_and_hides_compatibility_reads(
    memory_environment: _MemoryEnvironment,
) -> None:
    record = _candidate(memory_environment, text="Delete this governed fact.")
    created = _plan(
        memory_environment,
        operation_id="memory:create-before-delete",
        expected_revision=1,
        records=(record,),
        confirmed=(record.memory_id,),
    )
    memory_environment.store.commit_worker_candidates(
        created,
        authority=_authority(memory_environment, 1),
    )
    deletion = GovernedMemoryLifecycleMutation(
        memory_id=record.memory_id,
        expected_revision=2,
        previous_status=MemoryStatus.CONFIRMED,
        status=MemoryStatus.DELETED,
        updated_at=NOW + timedelta(minutes=2),
    )
    plan = WorkerMemoryMutationPlan.create(
        deployment_namespace=memory_environment.namespace,
        operation_id="memory:delete",
        session_id=memory_environment.session_id,
        expected_stream_revision=3,
        lifecycle_mutations=(deletion,),
        events=(
            _review_event(
                record,
                previous_status=MemoryStatus.CONFIRMED,
                status=MemoryStatus.DELETED,
                sequence=4,
                created_at=deletion.updated_at,
            ),
        ),
    )

    committed = memory_environment.store.commit_worker_candidates(
        plan,
        authority=_authority(memory_environment, 3),
    )

    assert committed.receipt.memories[0].status is MemoryStatus.DELETED
    assert committed.receipt.memories[0].revision == 3
    assert memory_environment.store.get(record.memory_id) is None
    assert memory_environment.store.list(
        MemoryQuery(
            repo_id="zebra-agent",
            visibility=MemoryVisibility.REPO,
            statuses=(),
        )
    ) == []
    authority = memory_environment.store.get_authority(
        record.memory_id,
        management=_management("memory:inspect-tombstone"),
    )
    assert isinstance(authority, GovernedMemoryTombstone)
    assert "text" not in type(authority).model_fields
    with psycopg.connect(memory_environment.dsn) as connection:
        assert connection.execute(
            """SELECT status, text, revision FROM governed_memory_records
            WHERE deployment_namespace = %s AND memory_id = %s""",
            (memory_environment.namespace, record.memory_id),
        ).fetchone() == ("deleted", None, 3)


@pytest.mark.parametrize("fault", ["fence", "stream"])
def test_stale_worker_authority_writes_nothing(
    memory_environment: _MemoryEnvironment,
    fault: str,
) -> None:
    expected = 1 if fault == "fence" else 0
    record = _candidate(memory_environment, text=f"Rejected stale {fault}.")
    plan = _plan(
        memory_environment,
        operation_id=f"memory:stale-{fault}",
        expected_revision=expected,
        records=(record,),
    )
    authority = _authority(memory_environment, expected)
    if fault == "fence":
        authority = authority.model_copy(
            update={
                "lease_fence": authority.lease_fence.model_copy(
                    update={"fencing_token": authority.lease_fence.fencing_token + 1}
                )
            }
        )
    before = _aggregate_state(memory_environment)

    with pytest.raises((LeaseLostError, GovernedMemoryConflictError)):
        memory_environment.store.commit_worker_candidates(plan, authority=authority)

    assert _aggregate_state(memory_environment) == before


def test_lost_response_replays_canonical_receipt_with_regenerated_ids(
    memory_environment: _MemoryEnvironment,
) -> None:
    record = _candidate(memory_environment, text="Replay the frozen result.")
    plan = _plan(
        memory_environment,
        operation_id="memory:lost-response",
        expected_revision=1,
        records=(record,),
    )

    def lose_response() -> None:
        memory_environment.store.commit_worker_candidates(
            plan,
            authority=_authority(memory_environment, 1),
        )
        raise ConnectionError("response lost after commit")

    with pytest.raises(ConnectionError, match="response lost"):
        lose_response()
    stored_state = _aggregate_state(memory_environment)
    regenerated = record.model_copy(
        update={
            "memory_id": MemoryId(uuid4()),
            "created_at": NOW + timedelta(minutes=5),
            "updated_at": NOW + timedelta(minutes=5),
        }
    )
    retry = _plan(
        memory_environment,
        operation_id=plan.operation_id,
        expected_revision=1,
        records=(regenerated,),
    )

    replayed = memory_environment.store.commit_worker_candidates(
        retry,
        authority=_authority(memory_environment, 1),
    )

    assert replayed.replayed
    assert replayed.receipt.operation_id == plan.operation_id
    assert replayed.receipt.memories[0].memory_id == record.memory_id
    assert _aggregate_state(memory_environment) == stored_state


@pytest.mark.parametrize("corruption", ["result_digest", "event_anchor"])
def test_operation_replay_fails_closed_on_row_evidence_corruption(
    memory_environment: _MemoryEnvironment,
    corruption: str,
) -> None:
    record = _candidate(memory_environment, text=f"Corrupt {corruption}.")
    plan = _plan(
        memory_environment,
        operation_id=f"memory:corrupt-{corruption}",
        expected_revision=1,
        records=(record,),
    )
    memory_environment.store.commit_worker_candidates(
        plan,
        authority=_authority(memory_environment, 1),
    )
    with psycopg.connect(memory_environment.dsn) as connection:
        if corruption == "result_digest":
            connection.execute(
                """UPDATE governed_memory_operations SET result_digest = %s
                WHERE deployment_namespace = %s AND operation_id = %s""",
                ("f" * 64, memory_environment.namespace, plan.operation_id),
            )
        else:
            first = connection.execute(
                """SELECT event_id FROM session_events
                WHERE deployment_namespace = %s AND session_id = %s AND sequence = 0""",
                (memory_environment.namespace, memory_environment.session_id),
            ).fetchone()
            assert first is not None
            connection.execute(
                """UPDATE governed_memory_operations
                SET anchor_event_start = 0, anchor_event_end = 0,
                    anchor_start_event_id = %s, anchor_end_event_id = %s
                WHERE deployment_namespace = %s AND operation_id = %s""",
                (
                    first[0],
                    first[0],
                    memory_environment.namespace,
                    plan.operation_id,
                ),
            )

    with pytest.raises(GovernedMemoryConflictError):
        memory_environment.store.commit_worker_candidates(
            plan,
            authority=_authority(memory_environment, 1),
        )


def test_namespace_and_query_contracts_use_postgres_authority(
    memory_environment: _MemoryEnvironment,
) -> None:
    records = (
        _candidate(memory_environment, text="alpha zebra", offset=1),
        _candidate(
            memory_environment,
            text="beta zebra",
            memory_type=MemoryType.EPISODIC,
            offset=2,
        ),
        _candidate(memory_environment, text="unreviewed candidate", offset=3),
        _candidate(
            memory_environment,
            text="user memory",
            visibility=MemoryVisibility.USER,
            user_id="user-a",
            offset=4,
        ),
    )
    plan = _plan(
        memory_environment,
        operation_id="memory:query-fixtures",
        expected_revision=1,
        records=records,
        confirmed=tuple(record.memory_id for record in (*records[:2], *records[3:])),
    )
    memory_environment.store.commit_worker_candidates(
        plan,
        authority=_authority(memory_environment, 1),
    )
    final_stream_revision = 1 + len(plan.events)

    repo_all = memory_environment.store.list(
        MemoryQuery(
            repo_id="zebra-agent",
            visibility=MemoryVisibility.REPO,
            statuses=(),
        )
    )
    assert {record.memory_id for record in repo_all} == {
        record.memory_id for record in records[:3]
    }
    assert {
        record.memory_id
        for record in memory_environment.store.list(
            MemoryQuery(
                repo_id="zebra-agent",
                visibility=MemoryVisibility.REPO,
                text_query="zebra",
            )
        )
    } == {records[0].memory_id, records[1].memory_id}
    assert memory_environment.store.list(
        MemoryQuery(
            user_id="user-a",
            visibility=MemoryVisibility.USER,
        )
    )[0].memory_id == records[3].memory_id
    worker_entries = memory_environment.store.list_for_worker(
        MemoryQuery(
            repo_id="zebra-agent",
            visibility=MemoryVisibility.REPO,
        ),
        authority=_authority(memory_environment, final_stream_revision),
    )
    assert {entry.record.memory_id for entry in worker_entries} == {
        records[0].memory_id,
        records[1].memory_id,
    }
    with pytest.raises(GovernedMemoryConflictError, match="revision"):
        memory_environment.store.list_for_worker(
            MemoryQuery(
                repo_id="zebra-agent",
                visibility=MemoryVisibility.REPO,
            ),
            authority=_authority(memory_environment, final_stream_revision - 1),
        )

    other = _prepare_environment(memory_environment.dsn)
    other_record = _candidate(
        other,
        memory_id=records[0].memory_id,
        text="same ID in another namespace",
    )
    other.store.commit_worker_candidates(
        _plan(
            other,
            operation_id="memory:other-namespace",
            expected_revision=1,
            records=(other_record,),
        ),
        authority=_authority(other, 1),
    )
    assert memory_environment.store.get(records[0].memory_id).text == "alpha zebra"  # type: ignore[union-attr]
    assert other.store.get(records[0].memory_id).text == "same ID in another namespace"  # type: ignore[union-attr]
def _prepare_environment(dsn: str) -> _MemoryEnvironment:
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
    return _MemoryEnvironment(
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


def _candidate(
    environment: _MemoryEnvironment,
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


def _plan(
    environment: _MemoryEnvironment,
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
        _candidate_event(record, sequence=expected_revision + index + 1)
        for index, record in enumerate(records)
    ]
    events.extend(
        _review_event(
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


def _candidate_event(record: MemoryRecord, *, sequence: int) -> SessionEvent:
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


def _review_event(
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


def _authority(
    environment: _MemoryEnvironment,
    expected_revision: int,
) -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace=environment.namespace,
        session_id=environment.session_id,
        lease_fence=environment.lease.fence,
        expected_stream_revision=expected_revision,
    )


def _management(operation_id: str) -> GovernedMemoryManagementContext:
    return GovernedMemoryManagementContext(
        operation_id=operation_id,
        operator="memory-test",
        reason="validate governed Memory authority",
    )


def _aggregate_state(environment: _MemoryEnvironment) -> tuple[int, ...]:
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
