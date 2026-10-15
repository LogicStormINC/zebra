"""Transient read failures defer discovery; command/execution failures still escape."""

from uuid import uuid4

import psycopg
import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from zebra_agent_worker.command_consumer import SessionCommandConsumer

from tests.worker.test_command_consumer import _command_event, _ExecutionSpy, _seed_session


@pytest.mark.parametrize("stage", ["sessions", "event"])
@pytest.mark.parametrize("error", [TimeoutError, psycopg.OperationalError])
def test_read_failure_keeps_intent_and_cursor_for_next_poll(tmp_path, caplog, stage, error):
    stores, session_id, revision = _seed_session(tmp_path)
    command = SessionCommand(
        command_id=uuid4(),
        session_id=session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=revision,
        idempotency_key="read-retry",
    )
    event = _command_event(command, revision + 1)
    stores.events.append(event)
    execution = _ExecutionSpy(stores)
    failed = False

    def before(name):
        nonlocal failed
        if name == stage and not failed:
            failed = True
            raise error("private diagnostic must not be logged")

    def sessions(limit, after):
        before("sessions")
        return [stores.sessions.get_session(session_id)]

    def reader(identity, sequence):
        before("event")
        return event if sequence < event.sequence else None

    consumer = SessionCommandConsumer(
        stores, execution, command_sessions=sessions, next_command=reader
    )
    first = consumer.consume_once(worker_id="w", lease_ttl_seconds=30)
    assert first.status == "deferred" and consumer._scan_after is None
    assert error.__name__ in caplog.text and "private diagnostic" not in caplog.text
    assert not execution.calls and stores.events.list_for_session(session_id)[-1] == event
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "executed"
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "idle"
    assert len(execution.calls) == 1


def test_execution_timeout_is_not_misclassified_as_discovery(tmp_path):
    stores, identity, revision = _seed_session(tmp_path)
    command = SessionCommand(
        command_id=uuid4(),
        session_id=identity,
        kind=SessionCommandKind.RUN,
        expected_revision=revision,
        idempotency_key="write-timeout",
    )
    stores.events.append(_command_event(command, revision + 1))

    class Execution:
        def execute_session(self, *args, **kwargs):
            raise TimeoutError("unknown write outcome")

    consumer = SessionCommandConsumer(stores, Execution())
    with pytest.raises(TimeoutError, match="unknown write"):
        consumer.consume_once(worker_id="w", lease_ttl_seconds=30)
