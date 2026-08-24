from __future__ import annotations

import hashlib
import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.contracts.events import ContextCapsuleCreatedPayload
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextSourceEventRange,
)
from agent_core.domain.context_materialization import ContextMaterializationRequest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_storage import (
    PostgresContextMaterializationConflictError,
    PostgresContextMaterializationStore,
    PostgresEventStore,
    PostgresProjectionStore,
    apply_postgres_migrations,
)
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def deployment_namespace(postgres_dsn: str) -> Generator[str, None, None]:
    namespace = f"context-materialization-{uuid4()}"
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


class _IsolationProbeStore(PostgresContextMaterializationStore):
    transaction_settings: tuple[str, str] | None = None

    def _session_revision(
        self, connection: Any, request: ContextMaterializationRequest
    ) -> int:
        row = connection.execute(
            """
            SELECT current_setting('transaction_isolation') AS isolation,
                   current_setting('transaction_read_only') AS read_only
            """
        ).fetchone()
        self.transaction_settings = row["isolation"], row["read_only"]
        return super()._session_revision(connection, request)


def test_materializes_history_capsule_and_memory_in_one_generation(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id, capsule, memory = _seed_sources(postgres_dsn, deployment_namespace)
    request = _request(session_id, revision=5, capsule_id=capsule.capsule_id)

    result = PostgresContextMaterializationStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    ).materialize(request)

    assert result.session_revision == 5
    assert [(item.sequence, item.role) for item in result.history] == [
        (1, "user"),
        (3, "assistant"),
    ]
    assert result.active_capsule == capsule
    assert [entry.record.memory_id for entry in result.memories] == [memory.record.memory_id]
    assert result.generation.memory_revisions == ((str(memory.record.memory_id), 1),)


def test_materialization_uses_one_read_only_repeatable_read_snapshot(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id, capsule, _ = _seed_sources(postgres_dsn, deployment_namespace)
    store = _IsolationProbeStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )

    store.materialize(_request(session_id, revision=5, capsule_id=capsule.capsule_id))

    assert store.transaction_settings == ("repeatable read", "on")


def test_materialization_history_limit_returns_the_recent_tail(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id, capsule, _ = _seed_sources(postgres_dsn, deployment_namespace)
    events = PostgresEventStore(postgres_dsn, deployment_namespace=deployment_namespace)
    events.append(
        SessionEvent.create(
            session_id=SessionId(session_id),
            sequence=6,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"tool_call_count": 1},
            created_at=_at(4),
        )
    )
    events.append(
        SessionEvent.create(
            session_id=SessionId(session_id),
            sequence=7,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": "Newest valid History message."},
            created_at=_at(5),
        )
    )
    projections = PostgresProjectionStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )
    session = projections.get_session(SessionId(session_id))
    assert session is not None
    projections.save_session(
        session.model_copy(update={"current_sequence": 7, "updated_at": _at(5)})
    )

    result = PostgresContextMaterializationStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    ).materialize(
        _request(
            session_id,
            revision=7,
            capsule_id=capsule.capsule_id,
            history_limit=2,
        )
    )

    assert [(item.sequence, item.role) for item in result.history] == [
        (3, "assistant"),
        (7, "user"),
    ]
    assert result.history_truncated is True


def test_materialization_excludes_automation_handoff_seed_from_history(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id, capsule, _ = _seed_sources(postgres_dsn, deployment_namespace)
    events = PostgresEventStore(postgres_dsn, deployment_namespace=deployment_namespace)
    events.append(
        SessionEvent.create(
            session_id=SessionId(session_id),
            sequence=6,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={
                "content": "Continue from the verified Task checkpoint.",
                "source": "session_handoff",
                "handoff_id": str(uuid4()),
                "principal_identity_hash": "0f" * 32,
                "actor_kind": "automation",
                "trust": "automation",
            },
            created_at=_at(4),
        )
    )
    projections = PostgresProjectionStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )
    session = projections.get_session(SessionId(session_id))
    assert session is not None
    projections.save_session(
        session.model_copy(update={"current_sequence": 6, "updated_at": _at(4)})
    )

    result = PostgresContextMaterializationStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    ).materialize(_request(session_id, revision=6, capsule_id=capsule.capsule_id))

    assert [(item.sequence, item.role) for item in result.history] == [
        (1, "user"),
        (3, "assistant"),
    ]
    assert result.history_truncated is False


def test_materialization_fails_closed_on_stale_session_or_capsule(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id, capsule, _ = _seed_sources(postgres_dsn, deployment_namespace)
    store = PostgresContextMaterializationStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )

    with pytest.raises(PostgresContextMaterializationConflictError, match="revision"):
        store.materialize(_request(session_id, revision=4, capsule_id=capsule.capsule_id))
    with pytest.raises(PostgresContextMaterializationConflictError, match="Capsule"):
        store.materialize(_request(session_id, revision=5, capsule_id="capsule-old"))


def test_materialization_filters_expired_and_candidate_memory_without_cross_namespace_reads(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id, capsule, _ = _seed_sources(postgres_dsn, deployment_namespace)
    _insert_memory(
        postgres_dsn,
        deployment_namespace,
        _memory(2, status=MemoryStatus.CANDIDATE),
    )
    _insert_memory(
        postgres_dsn,
        deployment_namespace,
        _memory(3, expires_at=_at(0), memory_type=MemoryType.PROCEDURE),
    )
    other_namespace = f"context-other-{uuid4()}"
    other_session, other_capsule, other_memory = _seed_sources(
        postgres_dsn, other_namespace, repo_id="other-repo"
    )
    try:
        result = PostgresContextMaterializationStore(
            postgres_dsn,
            deployment_namespace=deployment_namespace,
        ).materialize(_request(session_id, revision=5, capsule_id=capsule.capsule_id))
        assert [entry.record.repo_id for entry in result.memories] == ["repo-1"]
        assert other_session != session_id
        assert other_capsule.capsule_id == "capsule-5"
        assert other_memory.record.repo_id == "other-repo"
    finally:
        _delete_namespace(postgres_dsn, other_namespace)


def test_materialization_is_read_only(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id, capsule, _ = _seed_sources(postgres_dsn, deployment_namespace)
    before = _counts(postgres_dsn, deployment_namespace)
    PostgresContextMaterializationStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    ).materialize(_request(session_id, revision=5, capsule_id=capsule.capsule_id))
    assert _counts(postgres_dsn, deployment_namespace) == before


def _request(
    session_id: UUID,
    *,
    revision: int,
    capsule_id: str,
    history_limit: int = 20,
) -> ContextMaterializationRequest:
    return ContextMaterializationRequest(
        scope=OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="business-scope",
            allowed_session_ids=(str(session_id),),
        ),
        session_id=SessionId(session_id),
        expected_session_revision=revision,
        expected_active_capsule_id=capsule_id,
        history_limit=history_limit,
        as_of=_at(20),
        memory_query=MemoryQuery(
            repo_id="repo-1",
            visibility=MemoryVisibility.REPO,
            statuses=(MemoryStatus.CONFIRMED,),
            limit=10,
        ),
    )


def _seed_sources(
    dsn: str,
    namespace: str,
    *,
    repo_id: str = "repo-1",
) -> tuple[UUID, ContextCapsule, GovernedMemoryEntry]:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Context materialization",
            user_input="Read the current Context sources.",
            workspace_root=Path("/tmp/zebra-context"),
            created_at=_at(1),
        )
    )
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    for event in bootstrap.events:
        events.append(event)
    model_event = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=3,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload={"assistant_message": "History response"},
        created_at=_at(2),
    )
    events.append(model_event)
    capsule = ContextCapsule(
        capsule_id="capsule-5",
        objective="read Context sources",
        immediate_next="continue",
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=3),
        source_hash="a" * 64,
        confidence=1.0,
        created_at=_at(3),
    )
    compaction_event = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=4,
        event_type=EventType.CONTEXT_COMPACTED,
        actor=EventActor.SYSTEM,
        payload={
            "attempt_number": 1,
            "before_tokens": 100,
            "after_tokens": 50,
            "removed_message_count": 1,
            "retained_message_count": 2,
            "within_budget": True,
            "provenance": "test",
        },
        created_at=_at(3),
    )
    events.append(compaction_event)
    artifact_id = uuid4()
    assert capsule.source_event_range is not None
    capsule_event = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=5,
        event_type=EventType.CONTEXT_CAPSULE_CREATED,
        actor=EventActor.SYSTEM,
        payload=ContextCapsuleCreatedPayload(
            capsule_id=capsule.capsule_id,
            artifact_id=str(artifact_id),
            schema_version=capsule.version,
            source_hash=capsule.source_hash,
            source_event_range=capsule.source_event_range,
        ).model_dump(mode="json"),
        created_at=_at(3),
    )
    events.append(capsule_event)
    projected = bootstrap.session.model_copy(update={"current_sequence": 5, "updated_at": _at(3)})
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(projected)
    _insert_capsule(
        dsn,
        namespace,
        bootstrap.session.session_id,
        capsule,
        artifact_id,
        compaction_event,
        capsule_event,
    )
    memory = _memory(1, repo_id=repo_id)
    _insert_memory(dsn, namespace, memory)
    return bootstrap.session.session_id, capsule, memory


def _insert_capsule(
    dsn: str,
    namespace: str,
    session_id: SessionId,
    capsule: ContextCapsule,
    artifact_id: UUID,
    compaction_event: SessionEvent,
    capsule_event: SessionEvent,
) -> None:
    payload = capsule.model_dump(mode="json")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO context_capsule_artifacts (
                deployment_namespace, capsule_id, artifact_id, session_id, payload,
                payload_sha256, source_hash, compaction_event_id, capsule_event_id, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                namespace,
                capsule.capsule_id,
                artifact_id,
                session_id,
                Jsonb(payload),
                hashlib.sha256(capsule.model_dump_json().encode()).hexdigest(),
                capsule.source_hash,
                compaction_event.event_id,
                capsule_event.event_id,
                capsule.created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO active_context_projections (
                deployment_namespace, session_id, capsule_id, artifact_id,
                source_hash, event_sequence, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                namespace,
                session_id,
                capsule.capsule_id,
                artifact_id,
                capsule.source_hash,
                capsule_event.sequence,
                capsule_event.created_at,
            ),
        )


def _memory(
    revision: int,
    *,
    status: MemoryStatus = MemoryStatus.CONFIRMED,
    expires_at: datetime | None = None,
    repo_id: str = "repo-1",
    memory_type: MemoryType = MemoryType.PROJECT_RULE,
) -> GovernedMemoryEntry:
    record = MemoryRecord(
        memory_id=MemoryId(UUID(int=revision + 100)),
        memory_type=memory_type,
        text=f"Memory {revision}",
        confidence=1.0,
        status=status,
        visibility=MemoryVisibility.REPO,
        repo_id=repo_id,
        expires_at=expires_at,
        created_at=_at(-2),
        updated_at=_at(-1),
    )
    return GovernedMemoryEntry(
        deployment_namespace="placeholder",
        record=record,
        revision=revision,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=canonical_governed_memory_content_hash(record),
    )


def _insert_memory(dsn: str, namespace: str, entry: GovernedMemoryEntry) -> None:
    from agent_storage.postgres.governed_memory_rows import memory_values

    values = (*memory_values(namespace, entry),)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO governed_memory_records (
                deployment_namespace, memory_id, revision, memory_type, text, confidence,
                status, visibility, tenant_id, user_id, repo_id,
                authority_issuer, namespace_id, definition_id, source_session_id,
                source_event_start, source_event_end, source_commit_sha, superseded_by,
                expires_at, created_at, updated_at, creation_key, content_digest,
                provenance_digest
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            values,
        )


def _counts(dsn: str, namespace: str) -> tuple[int, int, int, int, int]:
    tables = (
        "session_events",
        "session_projections",
        "context_capsule_artifacts",
        "active_context_projections",
        "governed_memory_records",
    )
    counts: list[int] = []
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        for table in tables:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            ).fetchone()
            assert row is not None
            counts.append(int(row["count"]))
    return counts[0], counts[1], counts[2], counts[3], counts[4]


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        for table in (
            "active_context_projections",
            "context_capsule_artifacts",
            "governed_memory_records",
            "session_projections",
            "session_events",
            "session_streams",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )


def _at(minute: int) -> datetime:
    return datetime(2026, 8, 3, tzinfo=UTC) + timedelta(minutes=minute)
