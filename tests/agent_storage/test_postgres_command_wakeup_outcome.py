"""Read-only exact command outcomes; no broker or runtime activation."""

from uuid import uuid4

import psycopg
import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.command_wakeup import _validated_host_context
from agent_storage.postgres.command_wakeup_outcome import PostgresCommandOutcomeReader
from agent_storage.postgres.database import PostgresDatabase

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _enable, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg
from tests.agent_storage.test_postgres_command_wakeup_control import _control
from tests.agent_storage.test_postgres_command_wakeup_handoff import _handoff

dsn = _dsn
postgres_dsn = _pg


def _setup(dsn, kind="run"):
    session = _seed(dsn)
    _enable(dsn)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    event = _command(dsn, session.session_id, kind)
    with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as connection:
        context = _validated_host_context(connection, NAMESPACE, event)
    return event, context


def _command(dsn, session_id, kind="run"):
    sequence = _store(dsn).list_for_session(session_id)[-1].sequence + 1
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind(kind),
        expected_revision=sequence - 1,
        idempotency_key=str(uuid4()),
        payload={"run_id": "run-one"},
    )
    return _store(dsn).append(
        SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
        )
    )


def _read(dsn, event, context, **kwargs):
    reader = PostgresCommandOutcomeReader(dsn, deployment_namespace=NAMESPACE)
    return reader(
        kwargs.get("task_id", TaskId(event.session_id)), "run-one", event.event_id, context
    )


@pytest.mark.parametrize(
    "code,expected",
    [
        (None, "command_delivery_failed"),
        ("recovery_exhausted", "command_recovery_exhausted"),
    ],
)
def test_dead_pending_is_repeatable_read_only_safe_outcome(dsn, code, expected):
    event, context = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE session_command_pending SET status='dead', recovery_code=%s", (code,)
        )
        before = connection.execute(
            "SELECT row_to_json(p) FROM session_command_pending p"
        ).fetchall()
    assert _read(dsn, event, context) == expected
    assert _read(dsn, event, context) == expected
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute("SELECT row_to_json(p) FROM session_command_pending p").fetchall()
            == before
        )


def test_current_generation_only_and_publish_retry_not_business_failure(dsn):
    event, context = _setup(dsn)
    assert _read(dsn, event, context) is None
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_outbox SET status='dead'")
    assert _read(dsn, event, context) == "command_delivery_failed"
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET current_generation=1")
    assert _read(dsn, event, context) is None


def test_scope_task_and_ambiguous_executable_anchor_fail_closed(dsn):
    event, context = _setup(dsn)
    with pytest.raises(ValueError, match="identity"):
        _read(dsn, event, context.model_copy(update={"namespace_id": "other-tenant"}))
    with pytest.raises(ValueError, match="unique"):
        _read(dsn, event, context, task_id=TaskId(uuid4()))
    _command(dsn, event.session_id)
    with pytest.raises(ValueError, match="unique"):
        _read(dsn, event, context)


def test_control_only_unsupported_does_not_end_same_id_execution(dsn):
    control, context = _setup(dsn, "suspend")
    _control(dsn, control)
    assert _read(dsn, control, context) == "command_unsupported"
    execution = _command(dsn, control.session_id)
    assert _read(dsn, execution, context) is None


def test_durable_handoff_reconciliation_is_reported(dsn):
    event, context = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET origin='historical'")
    _handoff(dsn, event)
    assert _read(dsn, event, context) == "command_requires_reconciliation"


def test_canonical_terminal_wins_over_dead_delivery_with_fresh_read_only_grant(dsn):
    from datetime import UTC, datetime, timedelta

    event, context = _setup(dsn)
    _store(dsn).append(
        SessionEvent.create(
            session_id=event.session_id,
            sequence=event.sequence + 1,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={},
        )
    )
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_outbox SET status='dead'")
    fresh = context.model_copy(
        update={
            "scopes": ("event.read",),
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        }
    )
    assert _read(dsn, event, fresh) is None


def test_later_different_run_terminal_does_not_hide_old_command_failure(dsn):
    event, context = _setup(dsn)
    command = SessionCommand(
        session_id=event.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=event.sequence,
        idempotency_key="later-run",
        payload={"run_id": "different"},
    )
    _store(dsn).append(
        SessionEvent.create(
            session_id=event.session_id,
            sequence=event.sequence + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
        )
    )
    _store(dsn).append(
        SessionEvent.create(
            session_id=event.session_id,
            sequence=event.sequence + 2,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={},
        )
    )
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_outbox SET status='dead'")
    assert _read(dsn, event, context) == "command_delivery_failed"


def test_actual_composition_uses_its_dsn_for_guard_and_outcome(dsn):
    from zebra_agent_api.tenant_guard import task_access_response

    from tests.agent_storage.test_postgres_direct_control_api import _app

    event, context = _setup(dsn)
    app = _app(dsn)  # settings database_url is deliberately unreachable
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE broker_outbox SET status='dead'")
    assert task_access_response(app, str(event.session_id), context) is None
    assert app.command_outcome(TaskId(event.session_id), "run-one", event.event_id, context) == (
        "command_delivery_failed"
    )
    wrong = context.model_copy(update={"namespace_id": "other"})
    assert task_access_response(app, str(event.session_id), wrong).status_code == 404


def test_paired_real_handoff_child_terminal_precedes_old_outbox_error(dsn):
    from tests.agent_storage.test_postgres_command_wakeup_receipts import _refresh
    from tests.agent_storage.test_postgres_task_control_target import _handoff as rollover
    from tests.agent_storage.test_postgres_task_control_target import _suspended

    source = _suspended(dsn)
    event = _command(dsn, source)
    _refresh(dsn, source)
    store, request = rollover(dsn, source)
    child = store.commit(request).child_session_id
    events = _store(dsn).list_for_session(child)
    _store(dsn).append(
        SessionEvent.create(
            session_id=child,
            sequence=events[-1].sequence + 1,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={},
        )
    )
    with PostgresDatabase(dsn, deployment_namespace=NAMESPACE).connect() as connection:
        context = _validated_host_context(connection, NAMESPACE, event)
        connection.execute("UPDATE broker_outbox SET status='dead'")
    assert _read(dsn, event, context) is None


def test_source_head_outcome_shares_fresh_snapshot_and_requalifies_same_frontier(dsn):
    from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore

    from tests.agent_storage.test_postgres_command_wakeup_receipts import _refresh
    from tests.stream_storage.telemetry import Telemetry

    event, context = _setup(dsn)
    _refresh(dsn, event.session_id)
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE)
    telemetry = Telemetry()

    def capture(host):
        return tasks.read_stream_checkpoint_head(
            TaskId(event.session_id),
            "run-one",
            ordinary_version="ag-ui-v1",
            coverage_version="ag-ui-v1-coverage",
            host_context=host,
        )

    with telemetry.installed():
        telemetry.stage = "qualified-outcome"
        before = capture(context)
    assert before.command_outcome is None
    assert sum(v for k, v in telemetry.calls.items() if "/sql:" in k) == 2
    assert sum(v for k, v in telemetry.calls.items() if k.endswith("new_pg_socket")) == 1
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET status='dead'")
    after = capture(context)
    assert after.run.highwater == before.run.highwater
    assert after.command_outcome == "command_delivery_failed"
    with pytest.raises(ValueError, match="identity"):
        capture(context.model_copy(update={"workspace_ref": "wrong-workspace"}))
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE task_binding_snapshots SET binding_digest=%s", ("0" * 64,))
    with pytest.raises(ValueError, match="bounded Host scope"):
        capture(context)


def test_head_capture_requires_exact_reader_store_and_database(dsn):
    from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore

    class CustomReader(PostgresCommandOutcomeReader):
        def __call__(self, *args):
            return "command_unsupported"

    class CustomTasks(PostgresAgentTaskStore):
        pass

    reader = PostgresCommandOutcomeReader(dsn, deployment_namespace=NAMESPACE)
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace=NAMESPACE)
    assert reader.supports_source_head(tasks)
    assert not reader.supports_source_head(CustomTasks(dsn, deployment_namespace=NAMESPACE))
    custom = CustomReader(dsn, deployment_namespace=NAMESPACE)
    assert not custom.supports_source_head(tasks)
    assert custom(None) == "command_unsupported"
    alternate = PostgresAgentTaskStore(
        psycopg.conninfo.make_conninfo(dsn, application_name="different-outcome-composition"),
        deployment_namespace=NAMESPACE,
    )
    assert not reader.supports_source_head(alternate)
