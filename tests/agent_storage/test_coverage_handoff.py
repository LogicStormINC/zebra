"""Strict source history refuses v1 handoff through both public commit stores."""

import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import psycopg
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import (
    HandoffStorageConflictError,
    PostgresEventStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteSessionHandoffStore,
    SQLiteWorkspaceProjectionStore,
    bootstrap_control_plane_epoch,
)
from psycopg.types.json import Jsonb

from tests.agent_storage import test_postgres_session_handoffs as pg
from tests.agent_storage import test_session_handoffs as lite
from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.test_coverage_task_recovery import identity


@pytest.fixture(params=["sqlite", "postgres"])
def handoff(request, tmp_path):
    if request.param == "sqlite":
        path = tmp_path / "handoff.db"
        source = lite._seed_completed_source(path, tmp_path)
        env = SimpleNamespace(
            store=SQLiteSessionHandoffStore(path), source=source,
            events=SQLiteEventStore(path), projections=SQLiteProjectionStore(path),
            workspaces=SQLiteWorkspaceProjectionStore(path), seed=lite,
            connect=lambda: sqlite3.connect(path), namespace=None,
        )
    else:
        # Reuse the fixture that migrates only its own schema and drops it in finally.
        isolated = request.getfixturevalue("dsn")
        namespace = "coverage-handoff-test"
        bootstrap_control_plane_epoch(isolated, deployment_namespace=namespace)
        source = pg._seed_completed_source(isolated, namespace, tmp_path)
        env = SimpleNamespace(
            store=pg._store(isolated, namespace), source=source,
            events=PostgresEventStore(isolated, deployment_namespace=namespace),
            projections=PostgresProjectionStore(isolated, deployment_namespace=namespace),
            workspaces=PostgresWorkspaceProjectionStore(isolated, deployment_namespace=namespace),
            seed=pg, connect=lambda: psycopg.connect(isolated), namespace=namespace,
        )
    return env


def _set_admission(env, value):
    # Simulate persisted old/corrupt payloads without the new admission validator.
    prepared = next(event for event in env.events.list_for_session(env.source)
                    if event.event_type is EventType.TASK_PREPARED)
    payload = prepared.payload | {"coverage_admission": value}
    with env.connect() as connection:
        if env.namespace is None:
            connection.execute(
                "UPDATE session_events SET payload = ? WHERE event_id = ?",
                (json.dumps(payload), str(prepared.event_id)),
            )
        else:
            connection.execute(
                "UPDATE session_events SET payload = %s "
                "WHERE deployment_namespace = %s AND event_id = %s",
                (Jsonb(payload), env.namespace, prepared.event_id),
            )


def _later_omission(env):
    # Start this fixture's second preparation from a resumable suspended boundary.
    with env.connect() as connection:
        if env.namespace is None:
            connection.execute(
                "UPDATE session_events SET event_type = ? WHERE session_id = ? AND sequence = 4",
                (EventType.SESSION_SUSPENDED.value, str(env.source)),
            )
        else:
            connection.execute(
                "UPDATE session_events SET event_type = %s "
                "WHERE deployment_namespace = %s AND session_id = %s AND sequence = 4",
                (EventType.SESSION_SUSPENDED.value, env.namespace, env.source),
            )
    events = env.events.list_for_session(env.source)
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    payload = {key: value for key, value in prepared.payload.items()
               if key != "coverage_admission"}
    for event_type, event_payload in (
        (EventType.TASK_PREPARED, payload),
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 2}),
        (EventType.SESSION_COMPLETED, {"summary": "done again"}),
    ):
        event = SessionEvent.create(
            session_id=env.source, sequence=events[-1].sequence + 1,
            event_type=event_type, actor=EventActor.HARNESS,
            payload=event_payload, created_at=env.seed.NOW,
        )
        env.events.append(event)
        events.append(event)
    env.projections.save_session(rebuild_session(events))
    env.workspaces.save_workspace(rebuild_workspace(events))


def _aggregate(env):
    tables = [
        "session_events", "session_projections", "workspace_projections",
        "handoff_operations", "session_handoff_envelopes", "handoff_dispatch_outbox",
        "agent_tasks", "execution_segments",
    ]
    tables.append("session_lineage" if env.namespace is None else "session_streams")
    with env.connect() as connection:
        # Counts plus complete rows prove no projection/status mutation either.
        return {
            table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
            for table in tables
        }


def _assert_refused(env, request):
    before = _aggregate(env)
    counts = {table: len(rows) for table, rows in before.items()}
    with pytest.raises(HandoffStorageConflictError, match="strict coverage handoff is unsupported"):
        env.store.commit(request)
    after = _aggregate(env)
    assert {table: len(rows) for table, rows in after.items()} == counts
    assert after == before


@pytest.mark.parametrize("admission", [
    pytest.param("valid", id="strict-identity"),
    pytest.param({}, id="empty-object"),
    pytest.param({"history_ref": "broken"}, id="malformed-object"),
    pytest.param([], id="array"),
    pytest.param(False, id="false"),
    pytest.param(0, id="zero"),
    pytest.param("", id="empty-string"),
])
def test_non_null_persisted_admission_refuses_without_aggregate_writes(handoff, admission):
    _set_admission(handoff, identity().model_dump(mode="json")
                   if admission == "valid" else admission)
    _, request = handoff.seed._prepared_commit(handoff.store, handoff.source)
    _assert_refused(handoff, request)


def test_later_task_omission_cannot_erase_strict_history(handoff):
    _set_admission(handoff, identity().model_dump(mode="json"))
    _later_omission(handoff)
    assert "coverage_admission" not in [
        event for event in handoff.events.list_for_session(handoff.source)
        if event.event_type is EventType.TASK_PREPARED
    ][-1].payload
    _, request = handoff.seed._prepared_commit(handoff.store, handoff.source)
    _assert_refused(handoff, request)


def test_commit_reads_persisted_history_after_reservation(handoff):
    _, request = handoff.seed._prepared_commit(handoff.store, handoff.source)
    _set_admission(handoff, {})
    _assert_refused(handoff, request)


def test_replay_cannot_return_success_for_unsupported_strict_source(handoff):
    _, request = handoff.seed._prepared_commit(handoff.store, handoff.source)
    handoff.store.commit(request)
    # Represent a child committed by the old builder that dropped strict identity.
    _set_admission(handoff, identity().model_dump(mode="json"))
    _assert_refused(handoff, request)


@pytest.mark.parametrize("explicit_null", [False, True])
def test_legacy_omission_and_null_keep_commit_and_replay(handoff, explicit_null):
    if explicit_null:
        _set_admission(handoff, None)
    operation, request = handoff.seed._prepared_commit(handoff.store, handoff.source)
    first = handoff.store.commit(request)
    before = _aggregate(handoff)
    replay = handoff.store.commit(request)
    assert first.child_session_id == operation.target_session_id
    assert first.child_status == "ready" and not first.idempotent_replay
    assert replay == replace(first, idempotent_replay=True)
    assert _aggregate(handoff) == before


def test_request_text_cannot_supply_source_admission_authority(handoff):
    _, original = handoff.seed._prepared_commit(handoff.store, handoff.source)
    create = replace(
        original.create_request, idempotency_key="request-only",
        stage_prompt=json.dumps({"coverage_admission": identity().model_dump(mode="json")}),
    )
    facts = handoff.store.inspect_source_facts(handoff.source, at=handoff.seed.NOW)
    operation = handoff.store.reserve(
        create, request_hash=pg._request_hash(create),
        expected_source_stream_version=facts.stream_version,
        source_lease_fence=facts.lease_fence, authority_revision=facts.authority_revision,
        workspace_revision=facts.workspace_revision,
        task_profile_revision=facts.task_profile_revision,
        effective_depth_limit=facts.effective_depth_limit,
    )
    request = pg._commit_for_operation(operation, create)
    result = handoff.store.commit(request)
    assert result.child_status == "ready"
    prepared = handoff.events.list_for_session(result.child_session_id)[-1]
    assert "coverage_admission" not in prepared.payload
