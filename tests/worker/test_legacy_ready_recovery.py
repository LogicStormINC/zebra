"""A replayed command frontier is not evidence that execution began."""

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_storage import PostgresProjectionStore
from agent_storage.postgres.legacy_command_candidates import LegacyCommandCandidates

from tests.agent_storage.test_host_management import (
    host_management_dsn as postgres_dsn,  # noqa:F401
)
from tests.agent_storage.test_postgres_command_wakeup import (
    NAMESPACE,
    _seed,
    _store,
)
from tests.agent_storage.test_postgres_command_wakeup import (
    dsn as _dsn,
)
from tests.worker.test_command_consumer import _command_event
from tests.worker.test_command_recovery_postgres import _loop

dsn = _dsn


def projected_command(dsn, kind=SessionCommandKind.RUN):
    session = _seed(dsn)
    command = SessionCommand(
        session_id=session.session_id,
        kind=kind,
        expected_revision=session.current_sequence,
        idempotency_key="one-original",
        payload={"content": "one message"} if kind is SessionCommandKind.MESSAGE else {},
    )
    event = _command_event(command, session.current_sequence + 1)
    _store(dsn).append(event)
    projection = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    projection.save_session(
        session.model_copy(
            update={"current_sequence": event.sequence, "status": SessionStatus.READY}
        )
    )
    return session, event, projection


@pytest.mark.parametrize(
    "kind", [SessionCommandKind.RUN, SessionCommandKind.RESUME, SessionCommandKind.MESSAGE]
)
def test_ready_projected_original_is_discovered_without_a_new_command(dsn, kind):
    session, event, _ = projected_command(dsn, kind)
    before = _store(dsn).list_for_session(session.session_id)
    reader = LegacyCommandCandidates(dsn, deployment_namespace=NAMESPACE)
    assert [s.session_id for s in reader(8, None)] == [session.session_id]
    assert reader.next_command(session.session_id, event.sequence) == event
    assert _store(dsn).list_for_session(session.session_id) == before
    assert LegacyCommandCandidates(dsn, deployment_namespace="foreign")(8, None) == []


def test_new_worker_consumes_same_original_after_incompatible_setup_recovery(
    dsn, tmp_path, monkeypatch
):
    session, event, _ = projected_command(dsn)
    before = _store(dsn).list_for_session(session.session_id)
    # The image-level incompatible refusal is exercised by S1. Here a new actual
    # composed consumer must discover the persisted original after consumer replacement.
    consumer = _loop(dsn, tmp_path, monkeypatch)._command_consumer
    result = consumer.consume_once(worker_id="matching-worker", lease_ttl_seconds=30)
    assert result.status == "executed" and result.session_id == str(session.session_id)
    consumer._execution_service.execute_session.assert_called_once()
    assert consumer._execution_service.execute_session.call_args.args[0] == session.session_id
    assert _store(dsn).list_for_session(session.session_id) == before


@pytest.mark.parametrize("changed", ["new_execution_fact", "completed_projection"])
def test_equality_never_redispatches_an_executed_or_unknown_frontier(dsn, changed):
    session, event, projection = projected_command(dsn)
    if changed == "completed_projection":
        _store(dsn).append(
            SessionEvent.create(
                session_id=session.session_id,
                sequence=event.sequence + 1,
                event_type=EventType.SESSION_COMPLETED,
                actor=EventActor.HARNESS,
                payload={"summary": "durable completion"},
            )
        )
        projection.save_session(
            session.model_copy(
                update={"current_sequence": event.sequence + 1, "status": SessionStatus.COMPLETED}
            )
        )
    else:
        _store(dsn).append(
            SessionEvent.create(
                session_id=session.session_id,
                sequence=event.sequence + 1,
                event_type=EventType.HARNESS_ATTEMPT_STARTED,
                actor=EventActor.HARNESS,
                payload={"attempt_number": 1},
            )
        )
    reader = LegacyCommandCandidates(dsn, deployment_namespace=NAMESPACE)
    assert reader(8, None) == []
    assert reader.next_command(session.session_id, event.sequence) is None


def test_rejected_projected_frontier_remains_excluded(dsn):
    from agent_storage import PostgresIdempotencyStore
    from zebra_agent_worker.command_rejections import reject_command

    session, event, _ = projected_command(dsn)
    reject_command(
        PostgresIdempotencyStore(dsn, deployment_namespace=NAMESPACE), event, "invalid_command"
    )
    reader = LegacyCommandCandidates(dsn, deployment_namespace=NAMESPACE)
    assert reader(8, None) == []
    assert reader.next_command(session.session_id, event.sequence) is None
