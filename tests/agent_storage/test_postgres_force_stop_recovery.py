"""Real DB state-machine/security checks; exit ACK here is a unit-level injected fact."""

from datetime import timedelta

import psycopg
import pytest
from agent_core.domain.leases import LeaseLostError
from agent_runtime.force_stop_cleanup import recover_force_stops
from agent_storage import PostgresLeaseStore, bootstrap_control_plane_epoch
from agent_storage.postgres.force_stop_executors import register_executor
from agent_storage.postgres.force_stop_recovery import PostgresForceStopRecovery
from agent_storage.postgres.force_stops import PostgresForceStops
from zebra_agent_api import RouteAdapter

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_direct_control import _rows
from tests.agent_storage.test_postgres_direct_control_api import _app
from tests.agent_storage.test_postgres_force_stops import _force, _progress
from tests.agent_storage.test_postgres_runtime_instances import _setup

postgres_dsn = _pg_fixture
dsn = _dsn_fixture


def due(dsn):
    with psycopg.connect(dsn) as connection:
        connection.execute("""UPDATE agent_safety_overrides SET diagnostics=jsonb_set(
            diagnostics::jsonb,'{next_attempt_at}','\"2000-01-01T00:00:00+00:00\"')::text
            WHERE reason='user_force_stop'""")


def recover(dsn):
    return recover_force_stops(dsn, deployment_namespace=NAMESPACE, engine=None)


def test_ready_task_without_executor_closes_durably_and_never_requests_model(dsn):
    sid = _seed(dsn).session_id
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    adapter = RouteAdapter(_app(dsn))
    assert adapter.handle(_force(sid)).status_code == 202
    assert recover(dsn) == 1
    result = adapter.handle(_progress(sid)).body
    assert result["state"] == "stopped" and result["resources_released"]
    assert result["synchronization"] == "synchronized"
    assert _rows(dsn, "session_projections")[0]["status"] == "cancelled"
    events = _rows(dsn, "session_events")
    assert sum(e["event_type"] == "session_cancelled" for e in events) == 1
    assert not any(e["event_type"] == "model_request_started" for e in events)
    assert recover(dsn) == 0
    assert _rows(dsn, "session_events") == events
    assert adapter.handle(_force(sid)).status_code == 202  # original receipt, not new work
    assert adapter.handle(_progress(sid)).body == result


def test_unknown_exit_is_not_release_and_the_exact_late_ack_finishes_without_replay(dsn):
    lease = _setup(dsn)
    stops = PostgresForceStops(dsn, deployment_namespace=NAMESPACE)
    register_executor(stops.database, lease.session_id, lease.fence)
    with pytest.raises(LeaseLostError, match="already started"):
        register_executor(stops.database, lease.session_id, lease.fence)
    adapter = RouteAdapter(_app(dsn))
    adapter.handle(_force(lease.session_id))
    assert recover(dsn) == 0
    waiting = adapter.handle(_progress(lease.session_id)).body
    assert waiting["execution"] == "unconfirmed" and not waiting["resources_released"]
    assert waiting["lease"] == "revoked" and waiting["synchronization"] == "synchronized"
    assert _rows(dsn, "worker_leases")[0]["released_at"] is not None
    events = _rows(dsn, "session_events")
    stops.acknowledge_executor(
        lease.session_id, lease.fence.model_copy(update={"fencing_token": 999})
    )
    due(dsn)
    assert recover(dsn) == 0
    stops.acknowledge_executor(lease.session_id, lease.fence)
    due(dsn)
    assert recover(dsn) == 1
    assert adapter.handle(_progress(lease.session_id)).body["resources_released"]
    assert _rows(dsn, "session_events") == events
    with pytest.raises(LeaseLostError):
        register_executor(stops.database, lease.session_id, lease.fence)


def test_claim_is_exclusive_and_failure_budget_preserves_uncertain_outcome(dsn):
    lease = _setup(dsn)
    adapter = RouteAdapter(_app(dsn))
    adapter.handle(_force(lease.session_id))
    first = PostgresForceStopRecovery(dsn, deployment_namespace=NAMESPACE)
    second = PostgresForceStopRecovery(dsn, deployment_namespace=NAMESPACE)
    with first.claim(lease.session_id) as claim:
        assert claim
        with second.claim(lease.session_id) as other:
            assert other is None
    with psycopg.connect(dsn) as connection:
        connection.execute("""UPDATE agent_safety_overrides SET diagnostics=jsonb_set(
            diagnostics::jsonb,'{attempts}','15')::text""")
    assert recover(dsn) == 0
    result = adapter.handle(_progress(lease.session_id)).body
    assert result["state"] == "requires_reconciliation" and not result["resources_released"]
    assert first.pending() == []
    assert not any(e["event_type"] == "model_request_started" for e in _rows(dsn, "session_events"))


def test_cancelled_task_cannot_reacquire_a_lease(dsn):
    lease = _setup(dsn)
    adapter = RouteAdapter(_app(dsn))
    adapter.handle(_force(lease.session_id))
    recover(dsn)
    with pytest.raises(Exception, match="force.stop|cancel|terminal"):
        PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).acquire(
            lease.session_id, owner_instance_id="no-resurrection", ttl=timedelta(seconds=30)
        )


def _link(dsn, parent, child):
    from uuid import uuid4

    with psycopg.connect(dsn) as connection:
        digests = {}
        for task in (parent, child):
            digests[task] = connection.execute(
                "SELECT binding_digest FROM task_binding_snapshots "
                "WHERE task_id=%s ORDER BY binding_revision DESC LIMIT 1",
                (task,),
            ).fetchone()[0]
        connection.execute(
            """INSERT INTO subagent_delegation_links
            (deployment_namespace,delegation_id,idempotency_key,root_task_id,parent_task_id,
             parent_binding_digest,child_task_id,child_binding_digest)
            VALUES (%s,%s,'owned-delegation',%s,%s,%s,%s,%s)""",
            (NAMESPACE, str(uuid4()), parent, parent, digests[parent], child, digests[child]),
        )


def test_delegated_child_is_closed_but_invalid_cross_tenant_link_is_not_followed(dsn):
    from agent_core.domain.sessions import SessionStatus
    from agent_storage.postgres.projections import PostgresProjectionStore

    parent = _setup(dsn)
    valid = _seed(dsn).session_id
    foreign = _seed(dsn, tenant="foreign-tenant").session_id
    _link(dsn, parent.session_id, valid)
    stops = PostgresForceStops(dsn, deployment_namespace=NAMESPACE)
    register_executor(stops.database, parent.session_id, parent.fence)
    stops.acknowledge_executor(parent.session_id, parent.fence)
    adapter = RouteAdapter(_app(dsn))
    adapter.handle(_force(parent.session_id))
    assert recover(dsn) == 1
    projection = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    assert projection.get_session_status(valid) is SessionStatus.CANCELLED
    assert projection.get_session_status(foreign) is SessionStatus.READY
    # An incorrectly persisted cross-tenant edge is never cancellation authority.
    _link(dsn, valid, foreign)
    assert projection.get_session_status(foreign) is SessionStatus.READY
    assert not any(
        e["session_id"] == foreign and e["event_type"] == "session_cancelled"
        for e in _rows(dsn, "session_events")
    )


def test_already_completed_outcome_and_content_are_preserved(dsn):
    from agent_core.domain.events import EventActor, EventType, SessionEvent

    from tests.agent_storage.test_postgres_command_wakeup import _store

    lease = _setup(dsn)
    stops = PostgresForceStops(dsn, deployment_namespace=NAMESPACE)
    register_executor(stops.database, lease.session_id, lease.fence)
    stops.acknowledge_executor(lease.session_id, lease.fence)
    _store(dsn).append(
        SessionEvent.create(
            session_id=lease.session_id,
            sequence=5,
            actor=EventActor.HARNESS,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            payload={"attempt_number": 1},
        )
    )
    opened = next(
        e for e in _rows(dsn, "session_events") if e["event_type"] == "user_message_received"
    )
    _store(dsn).append(
        SessionEvent.create(
            session_id=lease.session_id,
            sequence=6,
            actor=EventActor.HARNESS,
            event_type=EventType.TURN_COMPLETED,
            payload={
                "turn_id": opened["payload"]["turn_id"],
                "turn_index": 0,
                "summary": "previously delivered result",
            },
        )
    )
    _store(dsn).append(
        SessionEvent.create(
            session_id=lease.session_id,
            sequence=7,
            actor=EventActor.SYSTEM,
            event_type=EventType.SESSION_COMPLETED,
            payload={"summary": "previously delivered result"},
        )
    )
    before = _rows(dsn, "session_events")
    adapter = RouteAdapter(_app(dsn))
    response = adapter.handle(_force(lease.session_id))
    assert response.status_code == 202, response.body
    assert recover(dsn) == 1
    assert _rows(dsn, "session_events") == before
    assert _rows(dsn, "session_projections")[0]["status"] == "completed"
    assert adapter.handle(_progress(lease.session_id)).body["resources_released"]


def test_binding_profile_revision_cannot_resurrect_stopped_task_or_its_children(dsn):
    from agent_core.domain.identifiers import TaskId
    from agent_core.domain.sessions import SessionStatus
    from agent_storage.postgres.projections import PostgresProjectionStore
    from agent_storage.postgres.task_admission import load_task_binding, save_task_binding

    lease = _setup(dsn)
    child = _seed(dsn).session_id
    _link(dsn, lease.session_id, child)
    stops = PostgresForceStops(dsn, deployment_namespace=NAMESPACE)
    register_executor(stops.database, lease.session_id, lease.fence)
    stops.acknowledge_executor(lease.session_id, lease.fence)
    adapter = RouteAdapter(_app(dsn))
    accepted = adapter.handle(_force(lease.session_id))
    for task in (lease.session_id, child):
        original = load_task_binding(dsn, deployment_namespace=NAMESPACE, task_id=TaskId(task))
        updated = original.model_copy(
            update={"binding_revision": 2, "zebra_policy_digest": "e" * 64}
        )
        save_task_binding(
            dsn, deployment_namespace=NAMESPACE, binding=updated, expected_previous_revision=1
        )
    projection = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
    assert projection.get_session_status(lease.session_id) is SessionStatus.CANCELLED
    assert projection.get_session_status(child) is SessionStatus.CANCELLED
    assert adapter.handle(_force(lease.session_id)).body == accepted.body
    assert recover(dsn) == 1
    assert adapter.handle(_progress(lease.session_id)).body["resources_released"]
