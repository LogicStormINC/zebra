"""Real handoff/Task-cancel serialization and immutable retry target selection."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityResolutionRequest,
)
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_storage import (
    PostgresLeaseStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
)
from agent_storage.postgres.session_handoff_transactions import commit_handoff_in_transaction
from agent_storage.postgres.session_handoffs import PostgresSessionHandoffStore
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from zebra_agent_api import RouteAdapter
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_command_wakeup_control import _intent
from tests.agent_storage.test_postgres_direct_control import _cancel, _rows
from tests.agent_storage.test_postgres_direct_control_api import _app, _request
from tests.agent_storage.test_postgres_lease_clock import _wait_locked, _worker_dsn
from tests.agent_storage.test_postgres_runtime_instances import SCOPE, _setup
from tests.agent_storage.test_postgres_session_handoffs import _prepared_commit

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _suspended(dsn):
    lease = _setup(dsn)
    events = list(_store(dsn).list_for_session(lease.session_id))
    for kind, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (EventType.SESSION_SUSPENDED, {"reason": "test_pause"}),
    ):
        events.append(
            _store(dsn).append(
                SessionEvent.create(
                    session_id=lease.session_id,
                    sequence=events[-1].sequence + 1,
                    event_type=kind,
                    actor=EventActor.HARNESS,
                    payload=payload,
                )
            )
        )
    PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE).save_session(
        rebuild_session(events)
    )
    PostgresWorkspaceProjectionStore(dsn, deployment_namespace=NAMESPACE).save_workspace(
        rebuild_workspace(events)
    )
    PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).release(
        lease.session_id, fence=lease.fence
    )
    return lease.session_id


def _handoff(dsn, source):
    store = PostgresSessionHandoffStore(dsn, deployment_namespace=NAMESPACE)
    _, request = _prepared_commit(store, source)
    envelope = request.envelope.model_copy(update={"created_at": datetime.now(UTC)})
    envelope = envelope.model_copy(update={"checksum": envelope.expected_checksum()})
    return store, replace(request, envelope=envelope)


@pytest.mark.parametrize("winner", ["handoff", "cancel"])
def test_handoff_and_cancel_serialize_both_winners_without_partial_lineage(dsn, winner):
    source = _suspended(dsn)
    _, request = _handoff(dsn, source)
    names = {name: f"task-control-{name}-{uuid4()}" for name in ("handoff", "cancel")}

    def handoff():
        return PostgresSessionHandoffStore(
            _worker_dsn(dsn, names["handoff"]), deployment_namespace=NAMESPACE
        ).commit(request)

    def cancel():
        return _cancel(_worker_dsn(dsn, names["cancel"]), source, task_id=TaskId(source))

    calls = {"handoff": handoff, "cancel": cancel}
    loser = "cancel" if winner == "handoff" else "handoff"
    with (
        psycopg.connect(dsn, autocommit=True) as observer,
        psycopg.connect(dsn) as blocker,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"{NAMESPACE}:{source}",)
        )
        first = pool.submit(calls[winner])
        _wait_locked(observer, names[winner])
        second = pool.submit(calls[loser])
        _wait_locked(observer, names[loser])
        blocker.commit()
        first.result(timeout=6)
        with pytest.raises(ValueError):
            second.result(timeout=6)
    operations = _rows(dsn, "direct_control_operations")
    segments = _rows(dsn, "execution_segments")
    if winner == "handoff":
        assert operations == []
        assert len(segments) == 2
        assert not _rows(dsn, "command_runtime_cleanup")
        assert not any(
            e.event_type is EventType.SESSION_CANCELLED
            for e in _store(dsn).list_for_session(source)
        )
    else:
        assert len(operations) == len(segments) == 1
        assert len(_rows(dsn, "command_runtime_cleanup")) == 1


def test_task_key_replays_original_cancel_after_real_rollover(dsn):
    source = _suspended(dsn)
    adapter = RouteAdapter(_app(dsn))
    first = adapter.handle(_request(source, key="pinned-cancel"))
    assert first.status_code == 200
    handoff, request = _handoff(dsn, source)
    successor = handoff.commit(request).child_session_id
    events = _rows(dsn, "session_events")
    operations = _rows(dsn, "direct_control_operations")
    leases = _rows(dsn, "worker_leases")
    assert adapter.handle(_request(source, key="pinned-cancel")) == first
    assert _rows(dsn, "direct_control_operations") == operations
    assert _rows(dsn, "session_events") == events
    assert _rows(dsn, "worker_leases") == leases
    assert operations[0]["session_id"] == source
    assert not any(
        e.event_type is EventType.SESSION_CANCELLED for e in _store(dsn).list_for_session(successor)
    )


def test_wrong_task_cannot_replay_an_existing_operation(dsn):
    source = _suspended(dsn)
    result = _cancel(dsn, source, task_id=TaskId(source), idempotency_key="same-key")
    other = _seed(dsn)
    with pytest.raises(ValueError, match="target changed"):
        _cancel(dsn, other.session_id, task_id=TaskId(other.session_id), idempotency_key="same-key")
    assert _rows(dsn, "direct_control_operations")[0]["terminal_event_id"] == result.event.event_id


def test_task_row_contention_is_safe_conflict_without_any_mutation(dsn):
    source = _suspended(dsn)
    before = _rows(dsn, "session_events"), _rows(dsn, "worker_leases")
    with psycopg.connect(dsn) as blocker:
        blocker.execute("SELECT * FROM agent_tasks FOR UPDATE")
        response = RouteAdapter(_app(dsn)).handle(_request(source))
        assert response.status_code == 409
        assert response.body["reason"] == "Task_cancellation_target_is_busy"
    assert (_rows(dsn, "session_events"), _rows(dsn, "worker_leases")) == before
    assert not _rows(dsn, "direct_control_operations")


def test_handoff_carries_frozen_host_identity_for_child_admission_and_cancellation(dsn):
    source = _suspended(dsn)
    # A legitimately expired frozen grant remains identity evidence, not authority to run.
    row = _rows(dsn, "task_binding_snapshots")[0]
    raw = row["snapshot_json"]
    context_type = TaskBindingSnapshot.model_validate(raw).host_capability.host_context
    context = context_type.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(minutes=1)}
    )
    raw["host_capability"].update(
        host_context=context.model_dump(mode="json"),
        grant_digest=host_context_digest(context),
        grant_expires_at=context.expires_at,
    )
    binding = TaskBindingSnapshot.model_validate(raw)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE task_binding_snapshots SET snapshot_json=%s,binding_digest=%s",
            (Jsonb(binding.model_dump(mode="json")), binding.binding_digest),
        )
    handoff, request = _handoff(dsn, source)
    child = handoff.commit(request).child_session_id
    events = _store(dsn).list_for_session(child)
    prepared = next(e for e in events if e.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["host_context"] == context.model_dump(mode="json")
    assert rebuild_session(events).namespace_id == context.namespace_id
    assert not any(e.event_type is EventType.EXECUTION_AUTHORITY_RESOLVED for e in events)
    with pytest.raises(ExecutionAuthorityResolutionError, match="expired"):
        BoundHostExecutionAuthorityResolver(binding=binding).resolve_for_attempt(
            ExecutionAuthorityResolutionRequest(
                session_id=child, attempt_number=1, scope=SCOPE, validated_at=datetime.now(UTC)
            )
        )
    command = _intent(dsn, child, "run")
    assert any(
        row["accepted_event_id"] == command.event_id
        for row in _rows(dsn, "session_command_pending")
    )
    result = RouteAdapter(_app(dsn)).handle(_request(source, key="cancel-child"))
    assert result.status_code == 200
    operation = _rows(dsn, "direct_control_operations")[0]
    assert operation["session_id"] == child


def test_invalid_observed_binding_cannot_be_laundered_by_a_later_valid_read(dsn):
    source = _suspended(dsn)
    _, request = _handoff(dsn, source)
    before = _rows(dsn, "session_events"), _rows(dsn, "execution_segments")

    class ChangingBindingConnection:
        """Return invalid version A once, then the real valid version B if reread."""

        def __init__(self, connection):
            self.connection = connection
            self.binding_reads = 0

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, query, params=None):
            cursor = self.connection.execute(query, params)
            if isinstance(query, str) and "snapshot_json" in query:
                self.binding_reads += 1
                if self.binding_reads == 1:
                    row = deepcopy(cursor.fetchone())
                    # Structurally valid snapshot, but its context no longer matches grant_digest.
                    row["snapshot_json"]["host_capability"]["host_context"]["workspace_ref"] = (
                        "unverified-workspace"
                    )

                    class ObservedRow:
                        def fetchone(self):
                            return row

                    return ObservedRow()
            return cursor

    with pytest.raises(ValueError, match="matching bounded Host scope"):
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            changing = ChangingBindingConnection(connection)
            commit_handoff_in_transaction(changing, NAMESPACE, request)
    assert changing.binding_reads == 1
    assert (_rows(dsn, "session_events"), _rows(dsn, "execution_segments")) == before
    assert _rows(dsn, "handoff_operations")[0]["status"] == "preparing"
