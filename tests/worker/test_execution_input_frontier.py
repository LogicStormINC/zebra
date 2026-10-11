"""Exact execution preparation must resume, never silently lose old constraints."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.ports.execution_inputs import ExecutionInputLimitExceeded, ExecutionInputState
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.worker_preparation import PreparationAdvanced
from agent_storage.execution_inputs import (
    ExecutionInputStore,
    execution_input_compaction_schema,
    execution_input_schema,
)
from agent_storage.leases import SQLiteLeaseStore
from zebra_agent_worker.execution_input_preparation import recover_execution_input_events
from zebra_agent_worker.execution_preparation import finish_preparation

from tests.agent_storage.test_worker_progress import output_payload, seed_progress


def setup_inputs(tmp_path):
    path = tmp_path / "inputs.sqlite"
    tasks, events, scope = seed_progress(path)
    leases = SQLiteLeaseStore(path)
    lease = leases.acquire(
        scope.task_id, owner_instance_id="input-worker", ttl=timedelta(seconds=60)
    )
    with tasks._database.connect() as connection:
        for statement in (*execution_input_schema(), *execution_input_compaction_schema()):
            connection.execute(statement)
    store = ExecutionInputStore(tasks._database, tasks, namespace="local")
    return tasks, events, lease, store


def append(events, lease, sequence, kind, payload):
    event = SessionEvent.create(
        session_id=lease.session_id,
        sequence=sequence,
        event_type=kind,
        actor=EventActor.USER,
        payload=payload,
    )
    events.append(event)
    return event


def test_resumable_prefix_preserves_old_user_constraints_and_latest_input(tmp_path):
    tasks, events, lease, store = setup_inputs(tmp_path)
    older = append(
        events, lease, 2, EventType.USER_MESSAGE_RECEIVED, {"content": "Never delete files"}
    )
    for sequence in range(3, 600):
        append(
            events,
            lease,
            sequence,
            EventType.MODEL_RESPONSE_DELTA,
            {
                "attempt_number": 1,
                "model_call_id": "stream",
                "delta_index": sequence,
                "content_delta": "x",
            },
        )
    latest = append(
        events, lease, 600, EventType.USER_MESSAGE_RECEIVED, {"content": "Inspect the repo"}
    )
    events.list_for_session = lambda *_: pytest.fail("whole-history hydration")
    with pytest.raises(PreparationAdvanced) as advanced:
        recover_execution_input_events(store=store, tasks=tasks, lease=lease, max_pages=1)
    assert advanced.value.through_sequence == 255
    assert advanced.value.highwater == 600
    head = store.read(lease)
    assert head.through_sequence == 255
    recovered = recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    assert older in recovered and latest in recovered
    assert not any(event.event_type is EventType.MODEL_RESPONSE_DELTA for event in recovered)
    assert store.read(lease).through_sequence == 600


def test_public_display_history_exceeds_capacity_without_entering_execution_inputs(tmp_path):
    tasks, events, lease, store = setup_inputs(tmp_path)
    older = append(
        events, lease, 2, EventType.USER_MESSAGE_RECEIVED, {"content": "Never delete files"}
    )
    for sequence in range(3, 2203):
        append(
            events,
            lease,
            sequence,
            EventType.PUBLIC_OUTPUT,
            output_payload(output=f"display:{sequence}", content="presentation " * 80),
        )
    latest = append(
        events, lease, 2203, EventType.USER_MESSAGE_RECEIVED, {"content": "Inspect only"}
    )
    source_count = 2204
    with tasks._database.connect() as connection:
        assert (
            connection.execute("SELECT SUM(event_bytes_bound) FROM session_events").fetchone()[0]
            > 1_048_576
        )
    events.list_for_session = lambda *_: pytest.fail("whole-history hydration")
    exact = finish_preparation(
        lambda: recover_execution_input_events(store=store, tasks=tasks, lease=lease, max_pages=1),
        lambda: None,
    )
    head = store.read(lease)
    assert exact == [*head.state.events]
    assert older in exact and latest in exact and len(exact) == 4
    assert head.through_sequence == head.state.session_revision == source_count - 1
    assert not any(event.event_type is EventType.PUBLIC_OUTPUT for event in exact)
    # A previous v1 head must not be trusted under the new selection contract.
    with tasks._database.connect() as connection:
        connection.execute("UPDATE execution_input_heads SET input_version='execution-input-v1'")
    assert store.read(lease).through_sequence == -1
    rebuilt = finish_preparation(
        lambda: recover_execution_input_events(store=store, tasks=tasks, lease=lease, max_pages=1),
        lambda: None,
    )
    assert rebuilt == exact


def test_forged_source_page_and_namespace_are_rejected(tmp_path):
    tasks, events, lease, store = setup_inputs(tmp_path)
    page = store.read_page(lease, -1, 1)
    fake = replace(
        page.events[0],
        event=page.events[0].event.model_copy(update={"payload": {"title": "forged"}}),
    )
    with pytest.raises(CheckpointConflict):
        store.advance(lease, replace(page, events=(fake, *page.events[1:])))
    assert store.read(lease).through_sequence == -1
    foreign = ExecutionInputStore(tasks._database, tasks, namespace="other")
    with pytest.raises(CheckpointConflict):
        foreign.read(lease)


def test_missing_dependency_and_timeout_without_commit_are_not_progress(tmp_path, monkeypatch):
    tasks, _, lease, store = setup_inputs(tmp_path)
    monkeypatch.setattr(tasks, "task_id_for_session", lambda *_: None)
    with pytest.raises(CheckpointNotReady) as missing:
        recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    assert not isinstance(missing.value, PreparationAdvanced)


def test_claimed_revision_includes_dropped_stream_deltas(tmp_path):
    tasks, events, lease, store = setup_inputs(tmp_path)
    append(
        events,
        lease,
        2,
        EventType.MODEL_RESPONSE_DELTA,
        {
            "attempt_number": 1,
            "model_call_id": "s",
            "delta_index": 0,
            "content_delta": "x",
        },
    )
    recovered = recover_execution_input_events(
        store=store, tasks=tasks, lease=lease, expected_session_revision=2
    )
    assert recovered[-1].sequence == 1
    from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot

    with pytest.raises(StaleExecutionSnapshot):
        recover_execution_input_events(
            store=store, tasks=tasks, lease=lease, expected_session_revision=1
        )


def test_fence_expiration_after_head_wait_rolls_back_creation(tmp_path, monkeypatch):
    from agent_core.domain.leases import LeaseLostError

    tasks, _, lease, store = setup_inputs(tmp_path)
    real_fence = store._fence
    calls = 0

    def expire_after_wait(connection, current):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise LeaseLostError("expired during business-row wait")
        real_fence(connection, current)

    monkeypatch.setattr(store, "_fence", expire_after_wait)
    with pytest.raises(LeaseLostError):
        store.advance(lease, store.read_page(lease, -1, 1))
    assert store.read(lease).through_sequence == -1


def test_input_count_ceiling_is_explicit_and_does_not_cut_oldest(tmp_path):
    tasks, _, lease, store = setup_inputs(tmp_path)
    page = store.read_page(lease, -1, 1)
    source = page.events[0].event
    from agent_core.ports.execution_inputs import ExecutionInputHead, fold_execution_inputs

    events = tuple(source.model_copy(update={"sequence": index}) for index in range(2048))
    with pytest.raises(ExecutionInputLimitExceeded, match="2048"):
        fold_execution_inputs(
            ExecutionInputHead(-1, ExecutionInputState(events=events)), page, lease
        )


def test_context_refresh_retries_only_suffix_under_ownership(tmp_path):
    from zebra_agent_worker.context_materialization import _refresh_inputs

    _, _, lease, _ = setup_inputs(tmp_path)
    reader = Mock(side_effect=[PreparationAdvanced("inputs", 1, 2), []])
    ownership = Mock()
    result = _refresh_inputs(Mock(), reader, lease, SimpleNamespace(_ownership_check=ownership))
    assert result == [] and reader.call_count == 2 and ownership.call_count == 2


def test_resume_more_than_five_slices_does_not_write_attempts(tmp_path, monkeypatch):
    tasks, events, lease, store = setup_inputs(tmp_path)

    # Force six durable slices with existing tiny pages; the retry generation
    # ceiling cannot govern preparation progress.
    # Native admission determines the authoritative bytes; do not fabricate pages.
    def native_tiny(current, after, through):
        key = store._key(current)
        with store._progress_connection() as connection:
            return store._page(connection, key, after, through, 1)

    monkeypatch.setattr(store, "read_page", native_tiny)
    for sequence in range(2, 8):
        append(
            events,
            lease,
            sequence,
            EventType.USER_MESSAGE_RECEIVED,
            {"content": f"constraint {sequence}"},
        )
    ownership = Mock()
    recovered = finish_preparation(
        lambda: recover_execution_input_events(store=store, tasks=tasks, lease=lease, max_pages=1),
        ownership,
    )
    assert ownership.call_count == 8
    assert not any(event.event_type is EventType.HARNESS_ATTEMPT_STARTED for event in recovered)


def test_exact_task_bootstrap_budgets_client_state_and_old_conversation(tmp_path):
    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.application.workspace_projection import rebuild_workspace
    from zebra_agent_worker.task_recovery import recover_client_state_evidence, recover_task

    from tests.worker.test_client_state_recovery import _event as client_event

    tasks, events, lease, store = setup_inputs(tmp_path)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Exact task",
            user_input="Never mutate",
            workspace_root=tmp_path,
            max_attempts=4,
            max_model_calls=7,
            max_tool_calls=9,
        )
    )
    prepared = next(
        event for event in bootstrap.events if event.event_type is EventType.TASK_PREPARED
    )
    append(events, lease, 2, EventType.TASK_PREPARED, prepared.payload)
    append(events, lease, 3, EventType.USER_MESSAGE_RECEIVED, {"content": "Never mutate"})
    append(events, lease, 4, EventType.USER_MESSAGE_RECEIVED, {"content": "Now inspect"})
    client = client_event(session_id=lease.session_id, sequence=5)
    events.append(client)
    exact = recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    task = recover_task(
        exact,
        workspace=rebuild_workspace(exact),
        fallback_title="fallback",
        attachment_reader=Mock(),
        client_state_evidence=recover_client_state_evidence(exact),
    )
    assert task.user_input == "Now inspect" and task.title == "Exact task"
    assert (task.max_attempts, task.max_model_calls, task.max_tool_calls) == (4, 7, 9)
    assert task.conversation_history[0].content == "Never mutate"
    assert task.client_state == recover_client_state_evidence([client])


def test_oversized_corrupt_checkpoint_is_rejected_before_body_read(tmp_path):
    tasks, _, lease, store = setup_inputs(tmp_path)
    store.advance(lease, store.read_page(lease, -1, 1))
    with tasks._database.connect() as connection:
        connection.execute("UPDATE execution_input_heads SET state_json=?", ("x" * 1_100_000,))
    with pytest.raises(CheckpointConflict, match="metadata"):
        store.read(lease)


def test_timeout_after_committed_prefix_carries_progress(tmp_path, monkeypatch):
    tasks, events, lease, store = setup_inputs(tmp_path)
    for sequence in range(2, 258):
        append(events, lease, sequence, EventType.USER_MESSAGE_RECEIVED, {"content": str(sequence)})
    original = store.read_page
    calls = 0

    def delayed(current, after, through):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError("cumulative budget spent")
        return original(current, after, through)

    monkeypatch.setattr(store, "read_page", delayed)
    with pytest.raises(PreparationAdvanced) as progress:
        recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    assert progress.value.through_sequence == store.read(lease).through_sequence == 255


@pytest.mark.parametrize("ready", [False, True])
def test_tail_header_timeout_after_commits_carries_real_frontier(tmp_path, monkeypatch, ready):
    tasks, events, lease, store = setup_inputs(tmp_path)
    if not ready:
        for sequence in range(2, 258):
            append(events, lease, sequence, EventType.USER_MESSAGE_RECEIVED, {"content": "exact"})
    original = tasks.read_task_header
    calls = 0

    def header(task_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError("tail header deadline")
        return original(task_id)

    monkeypatch.setattr(tasks, "read_task_header", header)
    with pytest.raises(PreparationAdvanced) as progress:
        recover_execution_input_events(store=store, tasks=tasks, lease=lease, max_pages=1)
    assert progress.value.through_sequence == store.read(lease).through_sequence
    assert progress.value.highwater == (1 if ready else 257)


@pytest.mark.parametrize("extra_events", [0, 258])
def test_ready_return_exit_timeout_reverifies_without_replaying_commits(
    tmp_path, monkeypatch, extra_events
):
    from zebra_agent_worker import execution_input_preparation as preparation
    from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot

    tasks, events, lease, store = setup_inputs(tmp_path)
    for sequence in range(2, extra_events + 2):
        append(events, lease, sequence, EventType.USER_MESSAGE_RECEIVED, {"content": "exact"})
    revision = extra_events + 1
    page_count = 1 if extra_events == 0 else 2
    original = preparation.task_io_deadline
    exits = 0

    @contextmanager
    def expired_on_first_exit(deadline):
        nonlocal exits
        with original(deadline):
            yield
            exits += 1
            if exits == 1:
                raise TimeoutError("deadline expired during ready context exit")

    monkeypatch.setattr(preparation, "task_io_deadline", expired_on_first_exit)
    advance = Mock(wraps=store.advance)
    monkeypatch.setattr(store, "advance", advance)
    with pytest.raises(PreparationAdvanced) as progress:
        recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    assert progress.value.through_sequence == progress.value.highwater == revision
    assert advance.call_count == page_count
    # The committed head is not permission to return unverified or stale inputs.
    with pytest.raises(StaleExecutionSnapshot):
        recover_execution_input_events(
            store=store, tasks=tasks, lease=lease, expected_session_revision=0
        )
    exact = recover_execution_input_events(
        store=store, tasks=tasks, lease=lease, expected_session_revision=revision
    )
    assert exact == list(store.read(lease).state.events)
    assert advance.call_count == page_count


@pytest.mark.parametrize("boundary", ["header", "head", "ready_exit"])
def test_timeout_without_own_durable_advance_is_not_progress(tmp_path, monkeypatch, boundary):
    from zebra_agent_worker import execution_input_preparation as preparation

    tasks, _, lease, store = setup_inputs(tmp_path)
    if boundary == "ready_exit":
        recover_execution_input_events(store=store, tasks=tasks, lease=lease)

        @contextmanager
        def expired(deadline):
            yield
            raise TimeoutError("read-only ready exit")

        monkeypatch.setattr(preparation, "task_io_deadline", expired)
    else:
        target, name = (tasks, "read_task_header") if boundary == "header" else (store, "read")
        monkeypatch.setattr(target, name, Mock(side_effect=TimeoutError("initial read")))
    with pytest.raises(TimeoutError):
        finish_preparation(
            lambda: recover_execution_input_events(store=store, tasks=tasks, lease=lease),
            lambda: None,
        )


def test_completed_prefix_marker_retries_only_verification_once():
    operation = Mock(side_effect=[PreparationAdvanced("inputs", 1, 1), ["verified"]])
    assert finish_preparation(operation, Mock()) == ["verified"]
    assert operation.call_count == 2
    operation = Mock(side_effect=PreparationAdvanced("inputs", 1, 1))
    with pytest.raises(ValueError, match="did not advance"):
        finish_preparation(operation, Mock())
    assert operation.call_count == 2


def test_event_view_finishes_only_reads_and_delegates_writes(tmp_path):
    from zebra_agent_worker.execution_input_preparation import ExecutionInputEventView

    _, _, lease, _ = setup_inputs(tmp_path)
    backend, ownership = Mock(), Mock()
    reader = Mock(side_effect=[PreparationAdvanced("inputs", 1, 2), []])
    view = ExecutionInputEventView(backend, reader, lease, ownership)
    assert view.list_for_session(lease.session_id) == []
    assert reader.call_count == ownership.call_count == 2
    view.append("canonical-write")
    backend.append.assert_called_once_with("canonical-write")
    with pytest.raises(ValueError, match="Session"):
        view.list_for_session("foreign-session")


def test_cloud_input_entry_uses_typed_checkpoint_without_history(tmp_path):
    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.application.session_projection import rebuild_session
    from agent_core.application.workspace_projection import rebuild_workspace
    from zebra_agent_worker.claims import ClaimedSession
    from zebra_agent_worker.execution_recovery import recover_execution_inputs
    from zebra_agent_worker.recovery import RecoveredSession

    tasks, events, lease, store = setup_inputs(tmp_path)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cloud input",
            user_input="Keep constraints",
            workspace_root=tmp_path,
        )
    )
    prepared = next(
        event for event in bootstrap.events if event.event_type is EventType.TASK_PREPARED
    )
    append(events, lease, 2, EventType.TASK_PREPARED, prepared.payload)
    append(events, lease, 3, EventType.USER_MESSAGE_RECEIVED, {"content": "Keep constraints"})
    source = events.list_for_session(lease.session_id)
    claimed = ClaimedSession(
        RecoveredSession(rebuild_session(source), rebuild_workspace(source), len(source), 3, False),
        lease,
    )
    events.list_for_session = lambda *_: pytest.fail("cloud whole-history hydration")
    context_store = Mock()
    context_store.get_active_capsule.return_value = None
    handoff = Mock()
    handoff.recover.return_value = None
    inputs = recover_execution_inputs(
        claimed=claimed,
        session_id=lease.session_id,
        started_at=lease.acquired_at,
        cloud_deployment=True,
        cloud_provider_continuation_factory=None,
        provider_continuation_store=Mock(),
        control_service=Mock(),
        recovery_service=Mock(),
        event_store=events,
        context_lifecycle_store=context_store,
        handoff_gate=handoff,
        artifact_payload_reader=Mock(),
        workspace_resolver=None,
        execution_input_store=store,
        tasks=tasks,
        namespace="local",
        ownership_check=Mock(),
    )
    assert inputs.task.user_input == "Keep constraints"
    assert inputs.execution_input_reader(lease) == source


def test_source_advancing_during_prefix_is_recaptured_before_readiness(tmp_path, monkeypatch):
    tasks, events, lease, store = setup_inputs(tmp_path)
    advance = store.advance
    tail = None

    def append_during_commit(current, page):
        nonlocal tail
        result = advance(current, page)
        if tail is None:
            tail = append(
                events, lease, 2, EventType.USER_MESSAGE_RECEIVED, {"content": "new constraint"}
            )
        return result

    monkeypatch.setattr(store, "advance", append_during_commit)
    exact = recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    assert tail in exact and store.read(lease).through_sequence == 2


def test_authority_append_is_not_repeated_when_recovery_and_inputs_advance(tmp_path, monkeypatch):
    from zebra_agent_worker.context_materialization import AttemptAuthorityEvidence

    _, _, lease, _ = setup_inputs(tmp_path)
    canonical_append = Mock(return_value=True)
    monkeypatch.setattr(
        "zebra_agent_worker.context_materialization.persist_attempt_authority", canonical_append
    )
    monkeypatch.setattr(
        "zebra_agent_worker.context_materialization.attempt_authority_scope", lambda *_: None
    )
    recovered = SimpleNamespace(session=SimpleNamespace(session_id=lease.session_id))
    claim = SimpleNamespace(lease=lease, recovery=recovered)
    recovery = Mock()
    recovery.recover_session.side_effect = [PreparationAdvanced("primary", 1, 2), recovered]
    reader = Mock(side_effect=[PreparationAdvanced("inputs", 1, 2), []])
    recorder = SimpleNamespace(_ownership_check=Mock())
    result, exact = AttemptAuthorityEvidence(None, None, None, recovery, Mock(), reader).persist(
        recorder,
        claim,
        [],
        session_id=lease.session_id,
        started_at=lease.acquired_at,
    )
    assert exact == [] and result.lease == lease
    assert canonical_append.call_count == 1
    assert recovery.recover_session.call_count == reader.call_count == 2


def test_exact_input_overflow_does_not_advance_or_discard_constraints(tmp_path):
    tasks, events, lease, store = setup_inputs(tmp_path)
    for sequence in range(2, 18):
        append(events, lease, sequence, EventType.USER_MESSAGE_RECEIVED, {"content": "约" * 30000})
    with pytest.raises(ExecutionInputLimitExceeded):
        recover_execution_input_events(store=store, tasks=tasks, lease=lease)
    assert store.read(lease).through_sequence < 17


def test_stale_page_cas_and_released_lease_cannot_advance(tmp_path):
    tasks, events, lease, store = setup_inputs(tmp_path)
    page = tasks.read_event_page(lease.session_id, -1)
    store.advance(lease, page)
    from agent_core.domain.leases import LeaseLostError
    from agent_core.ports.task_projection_checkpoints import CheckpointStale

    with pytest.raises(CheckpointStale):
        store.advance(lease, page)
    SQLiteLeaseStore(tmp_path / "inputs.sqlite").release(lease.session_id, fence=lease.fence)
    with pytest.raises(LeaseLostError):
        store.advance(lease, page)
