"""Strict source history refuses v1 handoff through both public commit stores."""

import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id
from agent_storage import (
    HandoffStorageConflictError,
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    PostgresWorkspaceProjectionStore,
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteSessionHandoffStore,
    SQLiteWorkspaceProjectionStore,
    bootstrap_control_plane_epoch,
)

from tests.agent_storage import test_postgres_session_handoffs as pg
from tests.agent_storage import test_session_handoffs as lite
from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.test_coverage_task_recovery import context, identity


@pytest.fixture(params=["sqlite", "postgres"])
def handoff(request, tmp_path):
    if request.param == "sqlite":
        path = tmp_path / "handoff.db"
        env = SimpleNamespace(
            store=SQLiteSessionHandoffStore(path), tasks=SQLiteAgentTaskStore(path),
            events=SQLiteEventStore(path), projections=SQLiteProjectionStore(path),
            workspaces=SQLiteWorkspaceProjectionStore(path), seed=lite,
            connect=lambda: sqlite3.connect(path), namespace=None,
        )
    else:
        # Reuse the fixture that migrates only its own schema and drops it in finally.
        isolated = request.getfixturevalue("dsn")
        namespace = "coverage-handoff-test"
        bootstrap_control_plane_epoch(isolated, deployment_namespace=namespace)
        env = SimpleNamespace(
            store=pg._store(isolated, namespace),
            tasks=PostgresAgentTaskStore(isolated, deployment_namespace=namespace),
            events=PostgresEventStore(isolated, deployment_namespace=namespace),
            projections=PostgresProjectionStore(isolated, deployment_namespace=namespace),
            workspaces=PostgresWorkspaceProjectionStore(isolated, deployment_namespace=namespace),
            seed=pg, connect=lambda: psycopg.connect(isolated), namespace=namespace,
        )
    bootstrap = SessionBootstrapService().build(SessionBootstrapCommand(
        title="Source stage", user_input="Complete source", workspace_root=tmp_path,
        policy_profile="local-safe", created_at=env.seed.NOW,
    ))
    env.source = bootstrap.session.session_id
    for event in bootstrap.events:
        env.events.append(event)
    for event_type, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (EventType.SESSION_SUSPENDED, {"reason": "fixture resumable boundary"}),
    ):
        env.events.append(SessionEvent.create(
            session_id=env.source,
            sequence=env.events.list_for_session(env.source)[-1].sequence + 1,
            event_type=event_type, actor=EventActor.HARNESS, payload=payload,
            created_at=env.seed.NOW,
        ))
    _project(env)
    env.tasks.ensure_for_session(env.source)
    return env


def _set_admission(env, value):
    # Persist an old/corrupt preparation at a resumable boundary, without
    # rewriting canonical history or disabling storage metadata guards.
    prepared = next(event for event in env.events.list_for_session(env.source)
                    if event.event_type is EventType.TASK_PREPARED)
    payload = prepared.payload | {"coverage_admission": value}
    if value is not None:
        payload["host_context"] = context().model_dump(mode="json")
    _append_preparation(env, payload, final=EventType.SESSION_SUSPENDED)


def _later_omission(env):
    events = env.events.list_for_session(env.source)
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    payload = {key: value for key, value in prepared.payload.items()
               if key != "coverage_admission"}
    _append_preparation(env, payload, final=EventType.SESSION_COMPLETED)


def _append_preparation(env, payload, *, final):
    events = env.events.list_for_session(env.source)
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    # model_copy deliberately represents retained legacy/malformed payloads;
    # EventStore append still allocates positions and enforces immutable fields.
    env.events.append(prepared.model_copy(update={
        "event_id": new_event_id(), "sequence": events[-1].sequence + 1, "payload": payload,
    }))
    for event_type, event_payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {
            "attempt_number": 1 + sum(
                event.event_type is EventType.HARNESS_ATTEMPT_STARTED for event in events
            ),
        }),
        (final, {"reason": "fixture resumable boundary"}
         if final is EventType.SESSION_SUSPENDED else {"summary": "done again"}),
    ):
        event = SessionEvent.create(
            session_id=env.source,
            sequence=env.events.list_for_session(env.source)[-1].sequence + 1,
            event_type=event_type, actor=EventActor.HARNESS,
            payload=event_payload, created_at=env.seed.NOW,
        )
        env.events.append(event)
    _project(env)


def _project(env):
    events = env.events.list_for_session(env.source)
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
    # Retain the legacy receipt and append strict source history; canonical
    # business fields cannot be rewritten after the handoff adopts the Task.
    events = handoff.events.list_for_session(handoff.source)
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    handoff.events.append(SessionEvent.create(
        session_id=handoff.source,
        sequence=events[-1].sequence + 1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload=prepared.payload | {
            "coverage_admission": identity().model_dump(mode="json"),
            "host_context": context().model_dump(mode="json"),
        },
        created_at=handoff.seed.NOW,
    ))
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
