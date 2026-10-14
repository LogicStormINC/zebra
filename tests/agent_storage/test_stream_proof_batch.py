"""Native snapshot freshness, source integrity and TaskIO cancellation/release."""

from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft
from agent_integrations.redis_transient_output import TransientOutputUnavailable
from agent_storage.postgres.stream_proof_batch import StreamProofReader
from agent_storage.postgres.task_io import task_io_deadline
from psycopg.conninfo import make_conninfo
from zebra_agent_worker.transient_output_composition import compose_transient_output_factory

from tests.worker.test_transient_output_composition_native import owned as _owned_fixture
from tests.worker.test_transient_output_composition_native import setup

owned = _owned_fixture


def opened(owned, monkeypatch):
    run, lease, recovery, _, settings = setup(owned, monkeypatch)
    recovery.persist_with(run.recorder.append_draft)(
        HarnessEventDraft(
            EventType.MODEL_REQUEST_STARTED,
            EventActor.HARNESS,
            {"model_call_id": "batch-call", "attempt_number": 1},
        )
    )
    writer = compose_transient_output_factory(
        run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
    )(recovery, lease)
    writer.start_public_call("batch-call", 1)
    assert not writer._failed
    return run, writer


@pytest.mark.parametrize("mutation", ["epoch", "token", "owner", "expiry", "index", "coverage"])
def test_native_issue_resolve_observes_intervening_source_mutation(owned, monkeypatch, mutation):
    run, writer = opened(owned, monkeypatch)
    issued = writer._gate.issue()
    with psycopg.connect(owned[0]) as connection:
        if mutation == "epoch":
            connection.execute(
                "UPDATE control_plane_epochs SET epoch=%s WHERE deployment_namespace=%s",
                (uuid4(), run.namespace),
            )
        elif mutation in {"token", "owner", "expiry"}:
            assignments = {
                "token": "fencing_token=fencing_token+1",
                "owner": "owner_instance_id='changed-owner'",
                "expiry": "expires_at=clock_timestamp()-interval '1 second'",
            }
            connection.execute(
                "UPDATE worker_leases SET "
                + assignments[mutation]
                + " WHERE deployment_namespace=%s AND session_id=%s",
                (run.namespace, run.session_id),
            )
        elif mutation == "index":
            connection.execute(
                "DELETE FROM task_event_index WHERE deployment_namespace=%s AND task_id=%s "
                "AND task_sequence=%s",
                (run.namespace, run.task_id, writer._gate.request_sequence),
            )
        else:
            from agent_core.domain.events import SessionEvent

            event = SessionEvent.create(
                session_id=run.session_id,
                sequence=run.recorder.session.current_sequence + 1,
                event_type=EventType.SESSION_CREATED,
                actor=EventActor.HARNESS,
                payload={"title": "privacy-marker"},
            )
            run.stores.events.append(
                event.model_copy(
                    update={
                        "event_type": EventType.TASK_PREPARED,
                        "payload": {"coverage_admission": None},
                    }
                )
            )
    try:
        with pytest.raises((TransientOutputUnavailable, ValueError)):
            writer._gate.resolve(issued)
    finally:
        writer.close()
        writer._port._client.close()


def test_native_snapshot_is_readonly_consistent_fresh_and_namespace_scoped(owned, monkeypatch):
    run, _, _, _, _ = setup(owned, monkeypatch)
    reader = StreamProofReader(owned[0], deployment_namespace=run.namespace)
    with reader.snapshot() as snapshot:
        assert (
            snapshot._connection.execute("SHOW transaction_read_only").fetchone()[
                "transaction_read_only"
            ]
            == "on"
        )
        first = snapshot.get(run.session_id)
        with psycopg.connect(owned[0]) as connection:
            connection.execute(
                "UPDATE worker_leases SET owner_instance_id='next-snapshot' "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (run.namespace, run.session_id),
            )
        assert snapshot.get(run.session_id) == first
    assert snapshot._connection.closed
    with pytest.raises(psycopg.OperationalError):
        snapshot.get(run.session_id)
    with reader.snapshot() as snapshot:
        assert snapshot.get(run.session_id).fence.owner_instance_id == "next-snapshot"
    foreign = StreamProofReader(owned[0], deployment_namespace=run.namespace + "-foreign")
    with foreign.snapshot() as snapshot:
        assert snapshot.read_task_header(run.task_id, require_source_coverage=True) is None
        assert snapshot.get(run.session_id) is None
    foreign_schema = StreamProofReader(
        make_conninfo(owned[0], options="-c search_path=pg_catalog"),
        deployment_namespace=run.namespace,
    )
    with pytest.raises(psycopg.errors.UndefinedTable):
        with foreign_schema.snapshot() as snapshot:
            snapshot.read_task_header(run.task_id, require_source_coverage=True)
    assert snapshot._connection.closed


def test_native_cumulative_deadline_cancels_and_releases_snapshot(owned, monkeypatch):
    reader = StreamProofReader(owned[0], deployment_namespace="timeout-proof")
    captured = []
    original = reader._database.connect_task_io

    def capture(*args, **kwargs):
        connection = original(*args, **kwargs)
        captured.append(connection)
        return connection

    monkeypatch.setattr(reader._database, "connect_task_io", capture)
    started = monotonic()
    with pytest.raises(TimeoutError), task_io_deadline(started + 0.1):
        with reader.snapshot() as snapshot:
            snapshot._connection.execute("SELECT pg_sleep(1)")
    assert monotonic() - started < 0.5
    assert captured and all(connection.closed for connection in captured)
    with reader.snapshot() as snapshot:
        snapshot._connection.execute("SELECT 1")
    assert all(connection.closed for connection in captured)


@pytest.mark.parametrize(
    "extension", ["native", "reader", "wrapped", "method", "subclass", "dsn", "namespace"]
)
def test_native_binding_snapshot_keeps_custom_hooks_and_database_scope(
    owned, monkeypatch, extension
):
    from functools import wraps

    from agent_storage.postgres.direct_control import PostgresDirectControl

    from tests.stream_storage.telemetry import Telemetry

    run, _, _, _, _ = setup(owned, monkeypatch)
    reader = StreamProofReader(owned[0], deployment_namespace=run.namespace)
    control = PostgresDirectControl(owned[0], deployment_namespace=run.namespace)
    baseline = control.load_task_binding(run.task_id)
    assert baseline is not None
    called = []

    def deny(task_id):
        called.append(task_id)
        return None

    if extension == "reader":
        control._binding_reader = deny
    elif extension in {"wrapped", "method"}:
        control.load_task_binding = (
            wraps(control.load_task_binding)(deny) if extension == "wrapped" else deny
        )
    elif extension == "subclass":

        class CustomControl(PostgresDirectControl):
            def load_task_binding(self, task_id):
                return deny(task_id)

        control = CustomControl(owned[0], deployment_namespace=run.namespace)
    elif extension == "dsn":
        control = PostgresDirectControl(
            make_conninfo(owned[0], application_name="snapshot-fallback"),
            deployment_namespace=run.namespace,
        )
    elif extension == "namespace":
        control = PostgresDirectControl(owned[0], deployment_namespace=run.namespace + "-foreign")
    telemetry = Telemetry()
    with telemetry.installed(), reader.snapshot() as snapshot:
        assert snapshot.get_session_namespace(run.session_id)[0]
        assert snapshot.read_session_highwater(run.session_id) >= 0
        result = control.read_task_binding_snapshot(snapshot, run.task_id)
    assert snapshot._connection.closed
    if extension in {"reader", "wrapped", "method", "subclass"}:
        assert result is None and called == [run.task_id]
    else:
        assert result == (None if extension == "namespace" else baseline)
    sockets = sum(v for k, v in telemetry.calls.items() if k.endswith("/new_pg_socket"))
    assert sockets == (2 if extension in {"dsn", "namespace"} else 1)
