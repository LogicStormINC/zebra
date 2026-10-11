"""Native exact MCP chain and raw governed-Memory evidence admission."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import psycopg
import pytest
from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionPlanner,
    memory_extraction_window,
)
from agent_core.application.memory_candidate_sources import candidates_from_session_event
from agent_core.application.memory_scopes import governed_memory_scope_from_events
from agent_core.application.session_projection import apply_event as apply_session
from agent_core.application.workspace_projection import apply_event as apply_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision,
    ExecutionAuthorityLimits,
    ExecutionAuthorityRevalidation,
    ExecutionAuthoritySnapshot,
)
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.memories import MemoryStatus
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.task_io import TaskIoConnection, task_io_deadline
from agent_storage.postgres.worker_replay_reader import (
    AUTHORITY_TYPES,
    WORKER_REPLAY_INDEX_SQL,
    PostgresWorkerReplayReader,
    WorkerReplayLimitExceeded,
)
from psycopg.types.json import Jsonb
from zebra_agent_worker.mcp_composition import load_worker_mcp_authority

from tests.worker import test_cloud_memory_finalization as memory_flow
from tests.worker.test_bounded_session_recovery import NS, seed
from tests.worker.test_bounded_session_recovery import native as native_fixture

native = native_fixture


@pytest.mark.parametrize(
    "case",
    [
        "commits_one_fenced_aggregate",
        "commits_one_fenced_aggregate_projection_ahead",
        "reconciles_lost_commit_response",
        "recovers_receipt_without_retrying_commit",
        "allows_a_closed_turn_side_chain",
    ],
)
def test_memory_reader_wiring_never_falls_back_to_whole_history(monkeypatch, case):
    finalize = memory_flow.finalize_cloud_memory

    def bounded(**kwargs):
        events = kwargs["event_store"]
        if case.endswith("_projection_ahead"):
            store = kwargs["memory_store"]
            commit = store.commit_worker_candidates

            def with_later_tail(plan, **authority):
                result = commit(plan, **authority)
                tail = SessionEvent.create(
                    session_id=events.session.session_id,
                    sequence=events.session.current_sequence + 1,
                    event_type=EventType.RUNTIME_CLEANUP_FAILED,
                    actor=EventActor.SYSTEM,
                    payload={},
                )
                events.events.append(tail)
                events.session = apply_session(events.session, tail)
                events.workspace = apply_workspace(events.workspace, tail)
                return result

            monkeypatch.setattr(store, "commit_worker_candidates", with_later_tail)
        # Explicit unit seam only; native constructor/fence/SQL are covered below.
        reader = Mock(spec=PostgresWorkerReplayReader)
        reader.memory_events.side_effect = lambda *a, **kw: list(events.events)
        reader.receipt_events.side_effect = lambda *a, **kw: [
            event for event in events.events if kw["after"] < event.sequence <= kw["through"]
        ]
        monkeypatch.setattr(events, "list_for_session", Mock(side_effect=AssertionError("history")))
        monkeypatch.setattr(
            events, "read_since", Mock(side_effect=AssertionError("unbounded tail"))
        )
        return finalize(**kwargs, replay_reader=reader)

    monkeypatch.setattr(memory_flow, "finalize_cloud_memory", bounded)
    getattr(
        memory_flow, f"test_cloud_memory_finalization_{case.removesuffix('_projection_ahead')}"
    )()


@pytest.fixture
def indexed(native):
    with psycopg.connect(native) as database:
        database.execute(WORKER_REPLAY_INDEX_SQL)
    return native


def snapshot(**changes):
    now = datetime.now(UTC)
    fields = dict(
        attempt_number=1,
        authority_issuer="local://trusted",
        namespace_id="scope",
        subject="worker",
        audience="zebra",
        granted_authorities=("agent.execute", "tool.mcp"),
        external_limits=ExecutionAuthorityLimits(),
        effective_limits=ExecutionAuthorityLimits(),
        issued_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(minutes=5),
        validated_at=now,
        source_authority_digest="a" * 64,
        policy_ref="worker@1",
        policy_version="1",
        policy_effective_digest="b" * 64,
    )
    fields.update(changes)
    return ExecutionAuthoritySnapshot(**fields)


def replace(dsn, sequence, event_type, payload, actor=EventActor.SYSTEM):
    with psycopg.connect(dsn) as database:
        database.execute(
            "UPDATE session_events SET event_type=%s,payload=%s,actor=%s WHERE sequence=%s",
            (event_type.value, Jsonb(payload), actor.value, sequence),
        )


@pytest.mark.parametrize("size", [1_000, 10_000, 100_000])
def test_native_mcp_frames_seek_only_exact_evidence_at_captured_head(indexed, monkeypatch, size):
    state = seed(indexed, size)
    authority = snapshot()
    replace(
        indexed,
        size - 2,
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "continue", "turn_id": "current", "turn_index": 1},
        EventActor.USER,
    )
    replace(indexed, size - 1, EventType.EXECUTION_AUTHORITY_RESOLVED, authority.to_event_payload())
    monkeypatch.setattr(
        state.events, "list_for_session", Mock(side_effect=AssertionError("history"))
    )
    reader = PostgresWorkerReplayReader(indexed, deployment_namespace=NS)
    for _ in range(2):
        actual = load_worker_mcp_authority(reader, state.session_id, "current")
        assert actual.snapshot == authority
    events = reader.authority_events(state.session_id)
    assert len(events) < 10
    assert all(event.event_type in AUTHORITY_TYPES for event in events)
    with pytest.raises(ValueError, match="current Turn"):
        load_worker_mcp_authority(reader, state.session_id, "other")
    with pytest.raises(ValueError, match="absent"):
        PostgresWorkerReplayReader(indexed, deployment_namespace="other").authority_events(
            state.session_id
        )
    state.events.list_for_session.assert_not_called()


@pytest.mark.parametrize("failure", ["expanded", "prior", "revoked", "expired", "reset"])
def test_native_authority_checks_entire_monotonic_chain_each_frame(indexed, failure):
    state = seed(indexed, 12)
    initial = snapshot()
    narrowed = snapshot(
        granted_authorities=("agent.execute",),
        issued_at=initial.issued_at,
        expires_at=initial.expires_at,
    )
    replace(
        indexed,
        4,
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "continue", "turn_id": "current", "turn_index": 1},
        EventActor.USER,
    )
    replace(indexed, 5, EventType.EXECUTION_AUTHORITY_RESOLVED, initial.to_event_payload())
    revalidation = ExecutionAuthorityRevalidation(
        attempt_number=1,
        prior_snapshot_digest=initial.snapshot_digest,
        source_authority_digest=initial.source_authority_digest,
        effective_snapshot_digest=narrowed.snapshot_digest,
        decision=ExecutionAuthorityDecision.NARROWED,
        validated_at=narrowed.validated_at,
        expires_at=narrowed.expires_at,
        effective_snapshot=narrowed,
    )
    replace(
        indexed, 6, EventType.EXECUTION_AUTHORITY_REVALIDATED, revalidation.model_dump(mode="json")
    )
    reader = PostgresWorkerReplayReader(indexed, deployment_namespace=NS)
    assert load_worker_mcp_authority(reader, state.session_id, "current").snapshot == narrowed
    payload = revalidation.model_dump(mode="json")
    payload["prior_snapshot_digest"] = narrowed.snapshot_digest
    if failure == "expanded":
        payload["effective_snapshot"] = initial.model_dump(mode="json")
        payload["effective_snapshot_digest"] = initial.snapshot_digest
    elif failure == "prior":
        payload["prior_snapshot_digest"] = "0" * 64
    elif failure == "revoked":
        payload.update(
            decision="revoked",
            reason_code="grant_revoked",
            effective_snapshot=None,
            effective_snapshot_digest=None,
        )
    elif failure == "expired":
        expired = snapshot(
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            validated_at=initial.issued_at,
            issued_at=initial.issued_at,
        )
        replace(indexed, 7, EventType.EXECUTION_AUTHORITY_RESOLVED, expired.to_event_payload())
    else:
        replace(
            indexed,
            7,
            EventType.TURN_COMPLETED,
            {"turn_id": "current", "turn_index": 1, "summary": "done"},
        )
    if failure in {"expanded", "prior", "revoked"}:
        replace(indexed, 7, EventType.EXECUTION_AUTHORITY_REVALIDATED, payload)
    with pytest.raises(ValueError):
        load_worker_mcp_authority(reader, state.session_id, "current")


def test_native_captured_frame_does_not_cache_away_next_tail_revocation(indexed, monkeypatch):
    state = seed(indexed, 12)
    initial = snapshot()
    replace(
        indexed,
        4,
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "continue", "turn_id": "current", "turn_index": 1},
        EventActor.USER,
    )
    replace(indexed, 5, EventType.EXECUTION_AUTHORITY_RESOLVED, initial.to_event_payload())
    revoked = ExecutionAuthorityRevalidation(
        attempt_number=1,
        prior_snapshot_digest=initial.snapshot_digest,
        source_authority_digest=initial.source_authority_digest,
        decision=ExecutionAuthorityDecision.REVOKED,
        reason_code="grant_revoked",
        validated_at=datetime.now(UTC),
    )
    execute = TaskIoConnection.execute
    appended = []

    def append_after_capture(connection, query, *args, **kwargs):
        cursor = execute(connection, query, *args, **kwargs)
        if isinstance(query, str) and query.startswith("SELECT current_version") and not appended:
            appended.append(True)
            state.events.append(
                SessionEvent.create(
                    session_id=state.session_id,
                    sequence=12,
                    event_type=EventType.EXECUTION_AUTHORITY_REVALIDATED,
                    actor=EventActor.SYSTEM,
                    payload=revoked.model_dump(mode="json"),
                )
            )
        return cursor

    monkeypatch.setattr(TaskIoConnection, "execute", append_after_capture)
    reader = PostgresWorkerReplayReader(indexed, deployment_namespace=NS)
    assert load_worker_mcp_authority(reader, state.session_id, "current").snapshot == initial
    with pytest.raises(ValueError, match="denied"):
        load_worker_mcp_authority(reader, state.session_id, "current")


def test_native_memory_window_and_source_provenance_equal_full_canonical_replay(indexed):
    state = seed(indexed, 1000)
    replace(
        indexed,
        8,
        EventType.TOOL_EXECUTION_COMPLETED,
        {
            "tool_name": "files.read",
            "status": "executed",
            "output": "# Local Commands\n- `make test`\n",
            "metadata": {"path": "AGENTS.md", "truncated": False},
        },
    )
    replace(
        indexed, 10, EventType.TURN_COMPLETED, {"turn_id": "old", "turn_index": 0, "summary": "old"}
    )
    replace(
        indexed,
        11,
        EventType.MEMORY_EXTRACTION_COMPLETED,
        {
            "completion_revision": 10,
            "candidate_count": 0,
            "lifecycle_count": 0,
            "outcome": "no_eligible_memory",
        },
    )
    replace(
        indexed,
        997,
        EventType.TOOL_EXECUTION_COMPLETED,
        {
            "tool_name": "files.read",
            "status": "executed",
            "output": "# Local Commands\n- `uv run pytest`\n",
            "metadata": {"path": "AGENTS.md", "truncated": False},
        },
    )
    replace(
        indexed,
        998,
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "Remember: use pytest", "turn_id": "new", "turn_index": 1},
        EventActor.USER,
    )
    replace(
        indexed,
        999,
        EventType.TURN_COMPLETED,
        {"turn_id": "new", "turn_index": 1, "summary": "new"},
    )
    reader = PostgresWorkerReplayReader(indexed, deployment_namespace=NS)
    authority = state.authority.model_copy(update={"expected_stream_revision": 999})
    full = state.events.list_for_session(state.session_id)
    evidence = reader.memory_events(state.session_id, authority=authority)
    assert memory_extraction_window(evidence) == memory_extraction_window(full) == 10
    assert governed_memory_scope_from_events(evidence, fallback_repo_id="repo") == (
        governed_memory_scope_from_events(full, fallback_repo_id="repo")
    )
    assert next(event for event in evidence if event.sequence == 8).payload == full[8].payload
    assert next(event for event in evidence if event.sequence == 998).event_id == full[998].event_id
    assert len(evidence) < 15
    now = datetime.now(UTC)
    old = candidates_from_session_event(
        full[8], repo_id="repo", user_id=None, tenant_id=None, created_at=now
    )
    assert len(old) == 1
    confirmed = (old[0].model_copy(update={"status": MemoryStatus.CONFIRMED}),)
    session = state.bootstrap.session.model_copy(
        update={
            "status": SessionStatus.COMPLETED,
            "current_sequence": 999,
        }
    )
    command = MemoryCandidateExtractionCommand(repo_id="repo", extracted_at=now, since_sequence=10)
    plans = [
        MemoryCandidateExtractionPlanner().plan(
            session=session,
            events=events,
            next_sequence=1000,
            command=command,
            confirmed_records=confirmed,
        )
        for events in (full, evidence)
    ]
    assert plans[0].stale_records == plans[1].stale_records
    assert len(plans[1].stale_records) == 1
    assert [
        (record.text, record.source_event_start, record.source_event_end)
        for record in plans[0].records
    ] == [
        (record.text, record.source_event_start, record.source_event_end)
        for record in plans[1].records
    ]
    with pytest.raises(LeaseLostError):
        reader.memory_events(
            state.session_id,
            authority=authority.model_copy(update={"deployment_namespace": "foreign"}),
        )
    state.leases.release(state.session_id, fence=state.lease.fence)
    with pytest.raises(LeaseLostError):
        reader.memory_events(state.session_id, authority=authority)


def test_native_exact_evidence_over_ceiling_fails_closed_instead_of_truncating(indexed):
    state = seed(indexed, 3000)
    with psycopg.connect(indexed) as database:
        database.execute(
            "UPDATE session_events SET event_type='approval_granted',payload='{}'::jsonb"
        )
    reader = PostgresWorkerReplayReader(indexed, deployment_namespace=NS)
    with pytest.raises(WorkerReplayLimitExceeded, match="2048"):
        reader.authority_events(state.session_id)


def test_reader_missing_or_unprepared_payload_bound_cannot_hydrate_unbounded_evidence(indexed):
    state = seed(indexed, 10)
    reader = PostgresWorkerReplayReader(indexed, deployment_namespace=NS)
    replace(
        indexed, 4, EventType.USER_MESSAGE_RECEIVED, {"content": "x" * 1_048_576}, EventActor.USER
    )
    with pytest.raises(WorkerReplayLimitExceeded, match="1MiB/page"):
        reader.authority_events(state.session_id)


def test_native_replay_inherits_cumulative_native_sql_deadline(indexed, monkeypatch):
    state = seed(indexed, 10)
    reader = PostgresWorkerReplayReader(indexed, deployment_namespace=NS)
    execute = TaskIoConnection.execute
    connections = []

    def slow(connection, query, *args, **kwargs):
        if isinstance(query, str) and "SELECT selected.sequence" in query:
            connections.append(connection)
            execute(connection, "SELECT pg_sleep(5)")
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(TaskIoConnection, "execute", slow)
    import time

    started = time.monotonic()
    with pytest.raises((TimeoutError, psycopg.errors.QueryCanceled)):
        with task_io_deadline(started + 0.2):
            reader.authority_events(state.session_id)
    assert time.monotonic() - started < 1
    assert connections and connections[0].closed
