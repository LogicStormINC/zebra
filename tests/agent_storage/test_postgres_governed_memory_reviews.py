from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryEntry,
    GovernedMemoryManagementContext,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.governed_memory_operations import (
    AdministrativeMemoryReviewRequest,
    GovernedMemoryReviewAction,
)
from agent_core.domain.governed_memory_receipts import GovernedMemoryCommitResult
from agent_core.domain.identifiers import MemoryId, SessionId, new_session_id
from agent_core.domain.leases import WorkerLease
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.ports.aggregate_mutation import (
    AdministrativeMutationCAS,
    WorkerMutationAuthority,
)
from agent_storage import (
    PostgresEventStore,
    PostgresGovernedMemoryStore,
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.governed_memory_rows import memory_values
from psycopg import sql
from psycopg.conninfo import make_conninfo

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)
CURSOR_SIGNING_KEY = b"zebra-governed-memory-test-key-32"


@dataclass(frozen=True)
class _ReviewEnvironment:
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
def review_environment(postgres_dsn: str) -> Generator[_ReviewEnvironment]:
    schema = f"governed_memory_review_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(dsn)
    yield _prepare_environment(dsn)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_admin_confirm_atomically_supersedes_current_scope_authority(
    review_environment: _ReviewEnvironment,
) -> None:
    old, (candidate,) = _insert_review_records(review_environment, candidates=1)
    _release_worker(review_environment)

    committed = review_environment.store.commit_administrative_review(
        _request(review_environment, candidate, operation_id="memory:review-confirm"),
        authority=_admin_authority(review_environment),
    )

    old_authority = _authority_record(review_environment, old.memory_id)
    candidate_authority = _authority_record(review_environment, candidate.memory_id)
    assert old_authority.record.status is MemoryStatus.SUPERSEDED
    assert old_authority.record.superseded_by == candidate.memory_id
    assert old_authority.revision == 3
    assert candidate_authority.record.status is MemoryStatus.CONFIRMED
    assert candidate_authority.revision == 2
    assert {
        item.memory_id: (item.revision, item.status) for item in committed.receipt.memories
    } == {
        old.memory_id: (3, MemoryStatus.SUPERSEDED),
        candidate.memory_id: (2, MemoryStatus.CONFIRMED),
    }
    assert committed.receipt.event_sequences == (2,)
    assert committed.receipt.session_revision == committed.receipt.projection_revision == 2
    event = _events(review_environment)[-1]
    assert event.sequence == 2
    assert event.payload["memory_id"] == str(candidate.memory_id)
    assert event.payload["superseded_memory_ids"] == [str(old.memory_id)]
    session = PostgresProjectionStore(
        review_environment.dsn,
        deployment_namespace=review_environment.namespace,
    ).get_session(review_environment.session_id)
    workspace = PostgresWorkspaceProjectionStore(
        review_environment.dsn,
        deployment_namespace=review_environment.namespace,
    ).get_workspace(review_environment.session_id)
    assert session is not None and session.current_sequence == 2
    assert workspace is not None and workspace.current_sequence == 2


def test_concurrent_reviewers_have_one_old_cas_winner(
    review_environment: _ReviewEnvironment,
) -> None:
    old, candidates = _insert_review_records(review_environment, candidates=2)
    _release_worker(review_environment)

    def review(candidate: MemoryRecord) -> tuple[MemoryId, GovernedMemoryCommitResult | Exception]:
        try:
            result = PostgresGovernedMemoryStore(
                review_environment.dsn,
                deployment_namespace=review_environment.namespace,
                cursor_signing_key=CURSOR_SIGNING_KEY,
            ).commit_administrative_review(
                _request(
                    review_environment,
                    candidate,
                    operation_id=f"memory:review:{candidate.memory_id}",
                ),
                authority=_admin_authority(review_environment),
            )
            return candidate.memory_id, result
        except GovernedMemoryConflictError as error:
            return candidate.memory_id, error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(review, candidates))

    assert sum(isinstance(result, GovernedMemoryCommitResult) for _, result in outcomes) == 1
    assert sum(isinstance(result, GovernedMemoryConflictError) for _, result in outcomes) == 1
    winner_id = next(
        memory_id
        for memory_id, result in outcomes
        if isinstance(result, GovernedMemoryCommitResult)
    )
    loser_id = next(
        candidate.memory_id for candidate in candidates if candidate.memory_id != winner_id
    )
    old_authority = _authority_record(review_environment, old.memory_id)
    winner = _authority_record(review_environment, winner_id)
    loser = _authority_record(review_environment, loser_id)
    assert old_authority.record.status is MemoryStatus.SUPERSEDED
    assert old_authority.record.superseded_by == winner_id
    assert winner.record.status is MemoryStatus.CONFIRMED
    assert loser.record.status is MemoryStatus.CANDIDATE
    state = _aggregate_state(review_environment)
    assert state[1:] == (1, 3, 2, 2, 2)


def test_active_worker_lease_blocks_admin_review_without_writes(
    review_environment: _ReviewEnvironment,
) -> None:
    _, (candidate,) = _insert_review_records(review_environment, candidates=1)
    before = _aggregate_state(review_environment)

    with pytest.raises(GovernedMemoryConflictError, match="active Lease"):
        review_environment.store.commit_administrative_review(
            _request(review_environment, candidate, operation_id="memory:active-lease"),
            authority=_admin_authority(review_environment),
        )

    assert _aggregate_state(review_environment) == before


def test_workspace_fault_rolls_back_full_admin_memory_aggregate(
    review_environment: _ReviewEnvironment,
) -> None:
    _, (candidate,) = _insert_review_records(review_environment, candidates=1)
    _release_worker(review_environment)
    before = _aggregate_state(review_environment)

    with _workspace_fault(review_environment):
        with pytest.raises(psycopg.Error, match="governed Memory projection fault"):
            review_environment.store.commit_administrative_review(
                _request(review_environment, candidate, operation_id="memory:fault"),
                authority=_admin_authority(review_environment),
            )

    assert _aggregate_state(review_environment) == before
    assert _authority_record(review_environment, candidate.memory_id).record.status is (
        MemoryStatus.CANDIDATE
    )


def _prepare_environment(dsn: str) -> _ReviewEnvironment:
    namespace = f"memory-review-{uuid4()}"
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    session_id = new_session_id()
    created = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.SESSION_CREATED,
        actor=EventActor.USER,
        payload={"title": "Governed Memory Review"},
        created_at=NOW,
    )
    prepared = SessionEvent.create(
        session_id=session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.SYSTEM,
        payload={
            "title": "Governed Memory Review",
            "user_input": "Validate administrative Memory review.",
            "workspace_root": "/tmp/governed-memory-review",
        },
        created_at=NOW,
    )
    PostgresEventStore(dsn, deployment_namespace=namespace).append(created)
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(
        rebuild_session([created])
    )
    lease_store = PostgresLeaseStore(dsn, deployment_namespace=namespace)
    lease = lease_store.acquire(
        session_id,
        owner_instance_id="memory-review-worker",
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
    return _ReviewEnvironment(
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


def _insert_review_records(
    environment: _ReviewEnvironment,
    *,
    candidates: int,
) -> tuple[MemoryRecord, tuple[MemoryRecord, ...]]:
    old = _memory_record(
        environment,
        text="Keep the old deployment procedure.",
        status=MemoryStatus.CONFIRMED,
    )
    candidate_records = tuple(
        _memory_record(
            environment,
            text=f"Use replacement deployment procedure {index}.",
            status=MemoryStatus.CANDIDATE,
            offset=index + 1,
        )
        for index in range(candidates)
    )
    with psycopg.connect(environment.dsn) as connection:
        _insert_entry(connection, environment.namespace, old, revision=2)
        for candidate in candidate_records:
            _insert_entry(connection, environment.namespace, candidate, revision=1)
    return old, candidate_records


def _memory_record(
    environment: _ReviewEnvironment,
    *,
    text: str,
    status: MemoryStatus,
    offset: int = 0,
) -> MemoryRecord:
    created_at = NOW + timedelta(seconds=offset)
    return MemoryRecord(
        memory_id=MemoryId(uuid4()),
        memory_type=MemoryType.PROCEDURE,
        text=text,
        confidence=0.9,
        status=status,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        source_session_id=environment.session_id,
        source_event_start=0,
        source_event_end=0,
        created_at=created_at,
        updated_at=created_at,
    )


def _insert_entry(
    connection: psycopg.Connection[tuple[object, ...]],
    namespace: str,
    record: MemoryRecord,
    *,
    revision: int,
) -> None:
    entry = GovernedMemoryEntry(
        deployment_namespace=namespace,
        record=record,
        revision=revision,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=canonical_governed_memory_content_hash(record),
    )
    connection.execute(
        """
        INSERT INTO governed_memory_records (
            deployment_namespace, memory_id, revision, memory_type, text,
            confidence, status, visibility, tenant_id, user_id, repo_id,
            source_session_id, source_event_start, source_event_end,
            source_commit_sha, superseded_by, expires_at, created_at,
            updated_at, creation_key, content_digest, provenance_digest
        ) VALUES ("""
        + ", ".join(["%s"] * 22)
        + ")",
        memory_values(namespace, entry),
    )


def _request(
    environment: _ReviewEnvironment,
    candidate: MemoryRecord,
    *,
    operation_id: str,
) -> AdministrativeMemoryReviewRequest:
    return AdministrativeMemoryReviewRequest.create(
        deployment_namespace=environment.namespace,
        operation_id=operation_id,
        session_id=environment.session_id,
        expected_stream_revision=1,
        memory_id=candidate.memory_id,
        expected_revision=1,
        action=GovernedMemoryReviewAction.CONFIRM,
        operator="memory-reviewer",
        reason="verified replacement procedure",
        created_at=NOW + timedelta(minutes=1),
    )


def _admin_authority(environment: _ReviewEnvironment) -> AdministrativeMutationCAS:
    return AdministrativeMutationCAS(
        deployment_namespace=environment.namespace,
        session_id=environment.session_id,
        expected_stream_revision=1,
    )


def _release_worker(environment: _ReviewEnvironment) -> None:
    PostgresLeaseStore(
        environment.dsn,
        deployment_namespace=environment.namespace,
    ).release(environment.session_id, fence=environment.lease.fence)


def _authority_record(
    environment: _ReviewEnvironment,
    memory_id: MemoryId,
) -> GovernedMemoryEntry:
    authority = environment.store.get_authority(
        memory_id,
        management=GovernedMemoryManagementContext(
            operation_id=f"inspect:{memory_id}",
            operator="memory-test",
            reason="verify administrative review",
        ),
    )
    assert isinstance(authority, GovernedMemoryEntry)
    return authority


def _events(environment: _ReviewEnvironment) -> list[SessionEvent]:
    return PostgresEventStore(
        environment.dsn,
        deployment_namespace=environment.namespace,
    ).list_for_session(environment.session_id)


def _aggregate_state(environment: _ReviewEnvironment) -> tuple[object, ...]:
    with psycopg.connect(environment.dsn) as connection:
        memories = connection.execute(
            """SELECT memory_id, revision, status, superseded_by, text
            FROM governed_memory_records WHERE deployment_namespace = %s
            ORDER BY memory_id""",
            (environment.namespace,),
        ).fetchall()
        row = connection.execute(
            """
            WITH target(namespace, session_id) AS (VALUES (%s, %s))
            SELECT
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
        return (tuple(memories), *(int(value) for value in row))


@contextmanager
def _workspace_fault(environment: _ReviewEnvironment) -> Iterator[None]:
    function = sql.Identifier(f"memory_review_fault_{uuid4().hex}")
    trigger = sql.Identifier(f"memory_review_fault_trigger_{uuid4().hex}")
    with psycopg.connect(environment.dsn) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE FUNCTION {}() RETURNS trigger AS $$
                BEGIN
                    IF NEW.deployment_namespace = {} THEN
                        RAISE EXCEPTION 'governed Memory projection fault';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            ).format(function, sql.Literal(environment.namespace))
        )
        connection.execute(
            sql.SQL(
                "CREATE TRIGGER {} BEFORE UPDATE ON workspace_projections "
                "FOR EACH ROW EXECUTE FUNCTION {}()"
            ).format(trigger, function)
        )
    try:
        yield
    finally:
        with psycopg.connect(environment.dsn) as connection:
            connection.execute(
                sql.SQL("DROP TRIGGER IF EXISTS {} ON workspace_projections").format(trigger)
            )
            connection.execute(sql.SQL("DROP FUNCTION IF EXISTS {}()").format(function))
