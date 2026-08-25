from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.clarifications import ClarificationContext
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.domain.plans import PlanStep, PlanStepStatus, SessionPlan
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_storage import (
    PostgresEventStore,
    PostgresMigrationError,
    PostgresProjectionConflictError,
    PostgresProjectionStore,
    apply_postgres_migrations,
)
from agent_storage.event_rows import SessionEventIdempotencyConflictError
from psycopg import sql
from psycopg.conninfo import make_conninfo


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def deployment_namespace(postgres_dsn: str) -> Generator[str]:
    namespace = f"test-{uuid4()}"
    yield namespace
    with psycopg.connect(postgres_dsn) as connection:
        for table in ("session_events", "session_projections", "session_streams"):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )


@pytest.fixture
def isolated_migration_dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"test_migration_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    yield make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_migrations_are_repeatable_and_checksum_recorded(
    isolated_migration_dsn: str,
) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(
            executor.map(
                apply_postgres_migrations,
                (isolated_migration_dsn, isolated_migration_dsn),
            )
        )
    with psycopg.connect(isolated_migration_dsn) as connection:
        row = connection.execute(
            """
            SELECT version, name, length(checksum)
            FROM zebra_schema_migrations
            WHERE version = 1
            """
        ).fetchone()
    assert row == (1, "event_and_projection_storage", 64)


def test_migrations_fail_closed_on_checksum_or_unknown_version(
    isolated_migration_dsn: str,
) -> None:
    apply_postgres_migrations(isolated_migration_dsn)
    with psycopg.connect(isolated_migration_dsn) as connection:
        connection.execute(
            "UPDATE zebra_schema_migrations SET checksum = 'invalid' WHERE version = 1"
        )
    with pytest.raises(PostgresMigrationError, match="does not match"):
        apply_postgres_migrations(isolated_migration_dsn)

    with psycopg.connect(isolated_migration_dsn) as connection:
        connection.execute("DELETE FROM zebra_schema_migrations WHERE version = 1")
        connection.execute(
            """
            INSERT INTO zebra_schema_migrations (version, name, checksum)
            VALUES (999999, 'unknown', 'unknown')
            """
        )
    with pytest.raises(PostgresMigrationError, match="unknown migration"):
        apply_postgres_migrations(isolated_migration_dsn)


def test_postgres_adapters_reject_invalid_namespaces(postgres_dsn: str) -> None:
    for namespace in ("", " untrimmed", "untrimmed "):
        with pytest.raises(ValueError, match="namespace"):
            PostgresEventStore(postgres_dsn, deployment_namespace=namespace)


def test_postgres_event_store_round_trips_and_isolates_namespaces(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    first_store = PostgresEventStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )
    second_store = PostgresEventStore(
        postgres_dsn,
        deployment_namespace=f"{deployment_namespace}-other",
    )
    event = _event(sequence=0, idempotency_key="create")

    first_store.append(event)
    second_store.append(event)

    assert first_store.list_for_session(event.session_id) == [event]
    assert second_store.list_for_session(event.session_id) == [event]
    assert first_store.read_since(event.session_id, sequence=0) == []

    _delete_namespace(postgres_dsn, f"{deployment_namespace}-other")


def test_postgres_event_store_allows_only_one_writer_per_expected_version(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id = new_session_id()
    store = append_store(postgres_dsn, deployment_namespace)
    initial = _event(session_id=session_id, sequence=0, idempotency_key="initial")
    store.append(initial)
    events = (
        _event(session_id=session_id, sequence=1, idempotency_key="writer-a"),
        _event(session_id=session_id, sequence=1, idempotency_key="writer-b"),
    )

    def append(event: SessionEvent) -> SessionEvent | ValueError:
        store = PostgresEventStore(
            postgres_dsn,
            deployment_namespace=deployment_namespace,
        )
        try:
            return store.append(event)
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(append, events))

    assert sum(isinstance(result, SessionEvent) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert len(store.list_for_session(session_id)) == 2


def test_postgres_event_store_concurrent_idempotent_retry_persists_one_event(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id = new_session_id()
    requests = (
        _event(session_id=session_id, sequence=0, idempotency_key="same-operation"),
        _event(session_id=session_id, sequence=0, idempotency_key="same-operation"),
    )

    def append(event: SessionEvent) -> SessionEvent:
        return PostgresEventStore(
            postgres_dsn,
            deployment_namespace=deployment_namespace,
        ).append(event)

    with ThreadPoolExecutor(max_workers=2) as executor:
        stored = tuple(executor.map(append, requests))

    assert stored[0] == stored[1]
    assert len(append_store(postgres_dsn, deployment_namespace).list_for_session(session_id)) == 1


def test_postgres_event_store_keeps_concurrent_sessions_independent(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_ids = (new_session_id(), new_session_id())
    events = tuple(
        _event(session_id=session_id, sequence=0, idempotency_key="create")
        for session_id in session_ids
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        stored = tuple(
            executor.map(
                append_store(postgres_dsn, deployment_namespace).append,
                events,
            )
        )

    assert stored == events
    store = append_store(postgres_dsn, deployment_namespace)
    assert all(store.list_for_session(event.session_id) == [event] for event in events)


def test_postgres_event_store_rejects_conflicting_idempotency_content(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    store = append_store(postgres_dsn, deployment_namespace)
    first = _event(sequence=0, idempotency_key="same-key", content="first")
    conflicting = _event(
        session_id=first.session_id,
        sequence=1,
        idempotency_key="same-key",
        content="different",
    )
    store.append(first)

    with pytest.raises(SessionEventIdempotencyConflictError):
        store.append(conflicting)

    assert store.list_for_session(first.session_id) == [first]


def test_postgres_event_insert_failure_rolls_back_stream_version(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    store = append_store(postgres_dsn, deployment_namespace)
    duplicate_event_id = uuid4()
    first = _event(sequence=0, event_id=duplicate_event_id)
    second_session = new_session_id()
    store.append(first)

    with pytest.raises(ValueError, match="duplicate or conflicting"):
        store.append(
            _event(
                session_id=second_session,
                sequence=0,
                event_id=duplicate_event_id,
            )
        )

    valid = _event(session_id=second_session, sequence=0)
    assert store.append(valid) == valid


def test_postgres_event_id_reuse_on_same_sequence_fails_closed(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    from agent_storage import SessionEventSequenceConflictError

    store = append_store(postgres_dsn, deployment_namespace)
    first = _event(sequence=0)
    store.append(first)

    with pytest.raises(ValueError, match="event id replayed") as raised:
        store.append(first.model_copy(update={"payload": {"content": "different"}}))

    assert not isinstance(raised.value, SessionEventSequenceConflictError)


def test_postgres_projection_store_round_trips_lists_and_isolates(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    store = PostgresProjectionStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )
    other = PostgresProjectionStore(
        postgres_dsn,
        deployment_namespace=f"{deployment_namespace}-other",
    )
    created_at = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
    ready = Session.create(title="ready", created_at=created_at).model_copy(
        update={"status": SessionStatus.READY, "updated_at": created_at}
    )
    waiting = Session.create(title="waiting", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "updated_at": created_at.replace(minute=1),
        }
    )
    for session in (waiting, ready):
        _seed_stream(postgres_dsn, deployment_namespace, session.session_id, through_sequence=0)
        assert store.save_session(session) == session

    assert store.get_session(ready.session_id) == ready
    assert other.get_session(ready.session_id) is None
    assert store.list_ready_sessions(limit=1) == [ready]
    assert store.list_waiting_approval_sessions() == [waiting]
    assert store.list_recent_sessions(limit=2) == [waiting, ready]


def test_postgres_projection_store_round_trips_nested_jsonb_contracts(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    store = PostgresProjectionStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )
    created_at = datetime(2026, 7, 28, 8, 5, tzinfo=UTC)
    session = Session.create(title="nested", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "current_sequence": 4,
            "approval_context": ApprovalContext(
                tool_name="tests.run",
                reason="verify",
                policy_profile="full_access",
                route="local_runtime",
                target="pytest",
                network_profile="none",
                scope=("tool:tests.run",),
            ),
            "clarification_context": ClarificationContext(
                clarification_id="00000000-0000-0000-0000-000000000124",
                tool_call_id="00000000-0000-0000-0000-000000000124",
                question="Continue?",
                choices=("Yes", "No"),
                assistant_message="Choose one option.",
                requested_at=created_at,
            ),
            "task_plan": SessionPlan(
                steps=(
                    PlanStep(
                        step_id="one",
                        content="Verify",
                        status=PlanStepStatus.IN_PROGRESS,
                    ),
                ),
                updated_at=created_at,
            ),
        }
    )

    _seed_stream(postgres_dsn, deployment_namespace, session.session_id, through_sequence=4)
    assert store.save_session(session) == session
    assert store.get_session(session.session_id) == session


def test_postgres_projection_store_rejects_stale_and_conflicting_versions(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    store = PostgresProjectionStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )
    created_at = datetime(2026, 7, 28, 8, 10, tzinfo=UTC)
    initial = Session.create(title="projection", created_at=created_at)
    advanced = initial.model_copy(
        update={
            "status": SessionStatus.RUNNING,
            "current_sequence": 2,
            "updated_at": created_at.replace(minute=2),
        }
    )
    conflicting = advanced.model_copy(update={"title": "different"})

    _seed_stream(postgres_dsn, deployment_namespace, initial.session_id, through_sequence=2)
    store.save_session(initial)
    store.save_session(advanced)
    assert store.save_session(advanced) == advanced
    with pytest.raises(PostgresProjectionConflictError, match="stale"):
        store.save_session(initial)
    with pytest.raises(PostgresProjectionConflictError, match="same sequence"):
        store.save_session(conflicting)
    assert store.get_session(initial.session_id) == advanced


def test_postgres_projection_store_rejects_projection_ahead_of_event_stream(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    store = PostgresProjectionStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )
    phantom = Session.create(
        title="phantom",
        created_at=datetime(2026, 7, 28, 8, 15, tzinfo=UTC),
    )

    with pytest.raises(PostgresProjectionConflictError, match="ahead"):
        store.save_session(phantom)


def test_postgres_projection_rebuilds_from_events(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    event_store = append_store(postgres_dsn, deployment_namespace)
    projection_store = PostgresProjectionStore(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
    )
    session_id = new_session_id()
    created_at = datetime(2026, 7, 28, 8, 20, tzinfo=UTC)
    for event in (
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "rebuild"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": "rebuild", "user_input": "continue"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=created_at,
        ),
    ):
        event_store.append(event)

    rebuilt = rebuild_session(event_store.list_for_session(session_id))
    projection_store.save_session(rebuilt)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            DELETE FROM session_projections
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (deployment_namespace, session_id),
        )
    assert projection_store.get_session(session_id) is None

    replayed = rebuild_session(event_store.list_for_session(session_id))
    assert projection_store.save_session(replayed) == rebuilt


def append_store(dsn: str, namespace: str) -> PostgresEventStore:
    return PostgresEventStore(dsn, deployment_namespace=namespace)


def _event(
    *,
    session_id: SessionId | None = None,
    sequence: int,
    idempotency_key: str | None = None,
    content: str = "continue",
    event_id: UUID | None = None,
) -> SessionEvent:
    event = SessionEvent.create(
        session_id=session_id or new_session_id(),
        sequence=sequence,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": content},
        idempotency_key=idempotency_key,
        created_at=datetime(2026, 7, 28, 8, 0, tzinfo=UTC),
    )
    return event.model_copy(update={"event_id": event_id}) if event_id else event


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        for table in ("session_events", "session_projections", "session_streams"):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )


def _seed_stream(
    dsn: str,
    namespace: str,
    session_id: SessionId,
    *,
    through_sequence: int,
) -> None:
    store = append_store(dsn, namespace)
    for sequence in range(through_sequence + 1):
        store.append(
            _event(
                session_id=session_id,
                sequence=sequence,
                idempotency_key=f"seed-{sequence}",
            )
        )
