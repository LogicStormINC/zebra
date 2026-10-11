"""Closed evidence compacts; exact safety inputs and source admission do not."""

from hashlib import sha256
from unittest.mock import Mock

import pytest
from agent_context.capsule import execution_evidence_context
from agent_context.projection_models import ToolResultTombstone
from agent_core.application.turn_projection import project_turns
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id
from agent_core.ports.execution_inputs import ExecutionInputLimitExceeded
from agent_core.ports.worker_preparation import PreparationAdvanced
from zebra_agent_worker.execution_input_preparation import (
    recover_execution_input_events,
    recover_execution_tool_output,
)
from zebra_agent_worker.execution_preparation import finish_preparation

from tests.worker.test_execution_input_frontier import setup_inputs


def closed_history(lease, *, models=0, tools=0, output="large evidence", closed=True):
    events = []

    def emit(kind, payload, actor=EventActor.HARNESS):
        event = SessionEvent(
            event_id=new_event_id(),
            session_id=lease.session_id,
            sequence=len(events) + 2,
            actor=actor,
            event_type=kind,
            payload=payload,
            created_at=lease.acquired_at,
        )
        events.append(event)
        return event

    emit(EventType.TASK_PREPARED, {"title": "Exact input", "max_attempts": 4})
    emit(
        EventType.USER_MESSAGE_RECEIVED,
        {
            "content": "Never delete files; 不得泄露凭据",
            "turn_id": "old",
            "origin": "human",
        },
        EventActor.USER,
    )
    emit(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    for index in range(models):
        payload = {"attempt_number": 1, "model_call_id": f"model:{index}"}
        emit(EventType.MODEL_REQUEST_STARTED, payload)
        emit(
            EventType.MODEL_RESPONSE_RECEIVED,
            {
                **payload,
                "assistant_message": "Exact prior decision: inspect only.",
                "tool_call_count": 0,
            },
        )
    for index in range(tools):
        payload = {"attempt_number": 1, "tool_call_id": f"tool:{index}", "tool_name": "files.read"}
        emit(EventType.TOOL_CALL_PROPOSED, {**payload, "arguments": {"path": f"file-{index}"}})
        emit(EventType.TOOL_EXECUTION_STARTED, payload)
        emit(
            EventType.TOOL_EXECUTION_COMPLETED,
            {
                **payload,
                "status": "executed",
                "output": output,
                "metadata": {"output_sha256": sha256(output.encode()).hexdigest()},
            },
        )
    if closed:
        emit(
            EventType.TURN_COMPLETED,
            {
                "turn_id": "old",
                "turn_index": 0,
                "closes_segment": False,
                "metadata": {"assistant_message": "Old turn result, kept exact."},
            },
        )
        emit(
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "Inspect the next file, keep every older constraint.",
                "turn_id": "new",
                "origin": "human",
            },
            EventActor.USER,
        )
        command = SessionCommand(
            session_id=lease.session_id,
            kind=SessionCommandKind.RUN,
            expected_revision=events[-1].sequence,
            idempotency_key="next-run",
            payload={"run_id": "next-run"},
        )
        emit(EventType.SESSION_COMMAND_ACCEPTED, command.event_payload(), EventActor.USER)
    return events


def prepare(store, tasks, lease, *, max_pages=1):
    return finish_preparation(
        lambda: recover_execution_input_events(
            store=store,
            tasks=tasks,
            lease=lease,
            max_pages=max_pages,
        ),
        lambda: None,
    )


def test_cold_history_beyond_event_cap_compacts_before_scanning_its_future_boundary(tmp_path):
    tasks, source, lease, store = setup_inputs(tmp_path)
    events = closed_history(lease, models=1100)
    for event in events:
        source.append(event)
    source.list_for_session = lambda *_: pytest.fail("whole history hydration")
    with pytest.raises(PreparationAdvanced):
        recover_execution_input_events(store=store, tasks=tasks, lease=lease, max_pages=1)
    first = store.read(lease)
    assert first.state.evidence is not None and first.through_sequence == 255
    assert first.state.evidence.closing_event_id == events[-3].event_id
    # Recreate the adapter like a crashed Worker; the next slice keeps the fence.
    resumed = type(store)(store._database, tasks, namespace=store.namespace)
    exact = prepare(resumed, tasks, lease)
    head = resumed.read(lease)
    assert head.through_sequence == events[-1].sequence
    assert head.state.evidence.model_request_count == 1100
    assert head.state.evidence.model_response_count == 1100
    assert head.state.evidence.archived_event_count == 2200
    assert len(exact) < 20 and len(head.state.encoded().encode()) < 1_048_576
    retained_source = [
        e
        for e in events
        if e.event_type
        not in {
            EventType.MODEL_REQUEST_STARTED,
            EventType.MODEL_RESPONSE_RECEIVED,
        }
    ]
    assert exact[2:] == retained_source
    assert project_turns(exact) == project_turns(events)
    assert head.state.evidence.capsule.decisions == ("Exact prior decision: inspect only.",)
    assert (
        "Never delete files; 不得泄露凭据" in head.state.evidence.capsule.protected_user_constraints
    )
    assert prepare(resumed, tasks, lease) == exact


def test_tool_bodies_beyond_one_mib_are_tombstoned_and_exactly_rehydrated(tmp_path):
    tasks, source, lease, store = setup_inputs(tmp_path)
    output = "Exact result 中文\n" * 9000
    events = closed_history(lease, tools=10, output=output)
    assert sum(len(e.model_dump_json().encode()) for e in events) > 1_048_576
    for event in events:
        source.append(event)
    prepare(store, tasks, lease)
    evidence = store.read(lease).state.evidence
    assert len(evidence.tools) == 10
    context = execution_evidence_context(evidence)
    assert context.metadata["current_run_budget_authority"] is False
    assert any(ToolResultTombstone.parse(line.split("\nArguments:")[0]) for line in context.details)
    assert output not in "\n".join(context.details)
    receipt = evidence.tools[-1]
    ownership = Mock()
    assert (
        recover_execution_tool_output(
            store=store,
            lease=lease,
            receipt=receipt,
            ownership_check=ownership,
        )
        == output
    )
    assert ownership.call_count == 2
    with pytest.raises(ValueError, match="not admitted"):
        recover_execution_tool_output(
            store=store,
            lease=lease,
            receipt=receipt.model_copy(update={"output_sha256": "0" * 64}),
            ownership_check=ownership,
        )


@pytest.mark.parametrize("reason", ["open", "missing_response", "failed_tool", "approval"])
def test_unsafe_or_unresolved_receipts_stay_exact(tmp_path, reason):
    tasks, source, lease, store = setup_inputs(tmp_path)
    events = closed_history(lease, models=1, tools=1, closed=reason != "open")
    if reason == "missing_response":
        events[4] = events[4].model_copy(update={"event_type": EventType.MODEL_RESPONSE_DELTA})
    elif reason == "failed_tool":
        events[7] = events[7].model_copy(
            update={"payload": {**events[7].payload, "status": "failed"}}
        )
    elif reason == "approval":
        events[4] = events[4].model_copy(
            update={
                "event_type": EventType.APPROVAL_REQUESTED,
                "payload": {"tool_call_id": "tool:0"},
            }
        )
    for event in events:
        source.append(event)
    exact = prepare(store, tasks, lease)
    if reason in {"open", "missing_response"}:
        assert events[3] in exact  # No inferred model response.
    if reason in {"open", "failed_tool", "approval"}:
        assert events[5] in exact and events[7] in exact


def test_uncompressible_constraints_fail_closed_without_admitting_the_oversized_event(tmp_path):
    tasks, source, lease, store = setup_inputs(tmp_path)
    event = closed_history(lease)[0].model_copy(
        update={
            "event_type": EventType.USER_MESSAGE_RECEIVED,
            "payload": {"content": "Uncompressible exact constraint " * 35000},
        }
    )
    source.append(event)
    with pytest.raises(ExecutionInputLimitExceeded):
        prepare(store, tasks, lease)
    assert store.read(lease).through_sequence == 1
    assert event not in store.read(lease).state.events


def test_future_boundary_outside_captured_highwater_cannot_admit_compaction(tmp_path):
    tasks, source, lease, store = setup_inputs(tmp_path)
    events = closed_history(lease, models=3)
    for event in events:
        source.append(event)
    page = store.read_page(lease, -1, events[-4].sequence)
    head = store.advance(lease, page)
    assert head.state.evidence is None
    assert events[3] in head.state.events


def test_current_run_and_handoff_markers_remain_exact(tmp_path):
    tasks, source, lease, store = setup_inputs(tmp_path)
    events = closed_history(lease, models=2)
    base = events[-1]
    tail = []
    for kind, payload in (
        (
            EventType.SESSION_HANDOFF_RECEIVED,
            {
                "handoff_id": str(new_event_id()),
                "parent_session_id": str(new_event_id()),
                "root_session_id": str(new_event_id()),
                "stage_index": 1,
                "artifact_id": str(new_event_id()),
                "checksum": "sha256:exact-handoff",
            },
        ),
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 2}),
        (EventType.MODEL_REQUEST_STARTED, {"attempt_number": 2, "model_call_id": "active"}),
        (
            EventType.MODEL_RESPONSE_RECEIVED,
            {
                "attempt_number": 2,
                "model_call_id": "active",
                "tool_call_count": 0,
                "assistant_message": "Current Run output cannot be archived.",
            },
        ),
        (EventType.CONTEXT_CONTINUATION_SELECTED, {"mode": "provider_native", "private": "exact"}),
        (EventType.EXECUTION_AUTHORITY_RESOLVED, {"exact_authority": "must survive"}),
        (EventType.SUBAGENT_DELEGATED, {"child_task_id": "exact-child"}),
        (EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED, {"exact_client": "must survive"}),
    ):
        tail.append(
            base.model_copy(
                update={
                    "event_id": new_event_id(),
                    "sequence": base.sequence + len(tail) + 1,
                    "event_type": kind,
                    "payload": payload,
                    "actor": EventActor.HARNESS,
                }
            )
        )
    for event in (*events, *tail):
        source.append(event)
    exact = prepare(store, tasks, lease)
    assert all(event in exact for event in tail)
    assert events[2] in exact  # First-attempt existence remains authoritative.
    evidence = store.read(lease).state.evidence
    assert evidence.model_request_count == evidence.model_response_count == 2
    assert "Current Run output cannot be archived." not in evidence.capsule.decisions


def test_new_authority_restores_only_exact_referenced_archived_exchange(tmp_path, monkeypatch):
    tasks, source, lease, store = setup_inputs(tmp_path)
    events = closed_history(lease, tools=3)
    for event in events:
        source.append(event)
    prepare(store, tasks, lease)
    before = store.read(lease)
    approval = events[-1].model_copy(
        update={
            "event_id": new_event_id(),
            "sequence": events[-1].sequence + 1,
            "event_type": EventType.APPROVAL_REQUESTED,
            "actor": EventActor.HARNESS,
            "payload": {"tool_call_id": "tool:0", "exact_authority": "not discarded"},
        }
    )
    source.append(approval)
    reads = []
    original = store._page

    def read(connection, key, after, through, limit=256):
        reads.append((after, through, limit))
        return original(connection, key, after, through, limit)

    monkeypatch.setattr(store, "_page", read)
    exact = prepare(store, tasks, lease)
    restored = [event for event in events if event.payload.get("tool_call_id") == "tool:0"]
    assert all(event in exact for event in (*restored, approval))
    assert not any(event.payload.get("tool_call_id") in {"tool:1", "tool:2"} for event in exact)
    evidence = store.read(lease).state.evidence
    assert tuple(tool.call_id for tool in evidence.tools) == ("tool:1", "tool:2")
    assert evidence.archived_event_count == before.state.evidence.archived_event_count - 3
    for event in restored:
        assert (event.sequence - 1, event.sequence, 1) in reads
    stable = store.read(lease)
    assert prepare(store, tasks, lease) == exact
    assert store.read(lease) == stable


def test_admitted_evidence_reaches_real_recovered_harness_task(tmp_path):
    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.application.session_projection import rebuild_session
    from agent_core.application.workspace_projection import rebuild_workspace
    from zebra_agent_worker.claims import ClaimedSession
    from zebra_agent_worker.execution_context import harness_task_for_recovered
    from zebra_agent_worker.execution_recovery import recover_execution_inputs
    from zebra_agent_worker.recovery import RecoveredSession

    tasks, source, lease, store = setup_inputs(tmp_path)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Evidence integration",
            user_input="Inspect only",
            workspace_root=tmp_path,
        )
    )
    payload = next(e.payload for e in bootstrap.events if e.event_type is EventType.TASK_PREPARED)
    history = closed_history(lease, models=2, tools=1)
    history[0] = history[0].model_copy(update={"payload": payload})
    for event in history:
        source.append(event)
    canonical = source.list_for_session(lease.session_id)
    claimed = ClaimedSession(
        RecoveredSession(
            rebuild_session(canonical),
            rebuild_workspace(canonical),
            len(canonical),
            history[-1].sequence,
            False,
        ),
        lease,
    )
    prepare(store, tasks, lease)
    source.list_for_session = lambda *_: pytest.fail("whole-history recovery")
    context_store, handoff = Mock(), Mock()
    context_store.get_active_capsule.return_value = None
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
        event_store=source,
        context_lifecycle_store=context_store,
        handoff_gate=handoff,
        artifact_payload_reader=Mock(),
        workspace_resolver=None,
        execution_input_store=store,
        tasks=tasks,
        namespace="local",
        ownership_check=lambda: None,
    )
    gateway, memories = Mock(), Mock()
    gateway.effective_mcp_tools = ()
    gateway.effective_skill_components = ()
    gateway.effective_skill_requirements = ()
    memories.list.return_value = []
    harness = harness_task_for_recovered(
        inputs.task,
        network_profile=inputs.task.network_profile,
        tool_gateway=gateway,
        memory_store=memories,
    )
    expected = execution_evidence_context(store.read(lease).state.evidence)
    assert expected in inputs.task.runtime_evidence
    assert expected in harness.runtime_evidence
    assert expected.metadata["current_run_budget_authority"] is False
    assert harness.max_attempts == inputs.task.max_attempts


def test_referenced_archived_checksum_conflict_rolls_back_frontier(tmp_path):
    tasks, source, lease, store = setup_inputs(tmp_path)
    history = closed_history(lease, tools=1)
    for event in history:
        source.append(event)
    prepare(store, tasks, lease)
    head = store.read(lease)
    receipt = head.state.evidence.tools[0].model_copy(update={"output_sha256": "0" * 64})
    corrupted = head.state.model_copy(
        update={"evidence": head.state.evidence.model_copy(update={"tools": (receipt,)})}
    ).encoded()
    with tasks._database.connect() as connection:
        connection.execute(
            "UPDATE execution_input_heads SET state_json=?,state_bytes=?",
            (corrupted, len(corrupted.encode())),
        )
    source.append(
        history[-1].model_copy(
            update={
                "event_id": new_event_id(),
                "sequence": history[-1].sequence + 1,
                "event_type": EventType.APPROVAL_REQUESTED,
                "payload": {"tool_call_id": "tool:0"},
            }
        )
    )
    with pytest.raises(ValueError, match="checksum"):
        prepare(store, tasks, lease)
    assert store.read(lease).through_sequence == head.through_sequence
    assert store.read(lease).state.events == head.state.events
