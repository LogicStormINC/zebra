"""Typed progress folding must preserve execution identity and publication truth."""

from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.harness.progress_recovery import fold_progress_page
from agent_core.harness.public_output import PublicOutputPolicy
from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointConflict
from agent_core.ports.worker_progress import (
    WorkerProgressHead,
    WorkerProgressScope,
    WorkerProgressState,
)


def head_and_page(*rows, state=None):
    task = TaskId(uuid4())
    scope = WorkerProgressScope("ns", task, "run", EventId(uuid4()), 1)
    entries = tuple(
        TaskEvent(
            task,
            n,
            SessionId(task),
            n,
            SessionEvent(
                event_id=scope.anchor_event_id if n == 1 else uuid4(),
                session_id=task,
                sequence=n,
                event_type=kind,
                payload=payload,
                actor=EventActor.HARNESS,
                created_at=datetime.now(UTC),
            ),
        )
        for n, (kind, payload) in enumerate(rows, 1)
    )
    return WorkerProgressHead(scope, 0, None, state or WorkerProgressState()), TaskEventPage(
        entries,
        0,
        len(entries),
        1024,
    )


def test_expression_budget_counts_requests_once_not_responses():
    head, page = head_and_page(
        (EventType.MODEL_REQUEST_STARTED, {"purpose": "public_expression"}),
        (
            EventType.MODEL_RESPONSE_RECEIVED,
            {"purpose": "public_expression", "response_stage": "public_expression"},
        ),
    )
    assert (
        fold_progress_page(
            head, page, output_published=lambda _: False
        ).head.state.expression_calls_used
        == 1
    )


def test_model_spoke_survives_tool_only_response_and_language_is_frozen():
    head, page = head_and_page(
        (EventType.USER_MESSAGE_RECEIVED, {"content": "请检查来源"}),
        (EventType.MODEL_RESPONSE_DELTA, {"content_delta": "已核对"}),
        (EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "Tool calls proposed."}),
        (EventType.USER_MESSAGE_RECEIVED, {"content": "Handoff"}),
    )
    state = fold_progress_page(head, page, output_published=lambda _: False).head.state
    assert state.model_spoke and state.chinese


@pytest.mark.parametrize("value", [None, 12, {}, "", "   "])
def test_missing_or_nontext_delta_does_not_become_public_model_speech(value):
    head, page = head_and_page((EventType.MODEL_RESPONSE_DELTA, {"content_delta": value}))
    assert not fold_progress_page(
        head, page, output_published=lambda _: False
    ).head.state.model_spoke


def test_policy_cannot_change_inside_run():
    head, page = head_and_page(
        (EventType.MODEL_REQUEST_STARTED, {"public_output_policy": asdict(PublicOutputPolicy())}),
        (
            EventType.MODEL_REQUEST_STARTED,
            {"public_output_policy": asdict(PublicOutputPolicy(version="other"))},
        ),
    )
    with pytest.raises(CheckpointConflict, match="policy changed"):
        fold_progress_page(head, page, output_published=lambda _: False)


def test_attempt_cannot_move_backwards():
    head, page = head_and_page(
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        state=WorkerProgressState(attempt_number=2),
    )
    with pytest.raises(CheckpointConflict, match="backwards"):
        fold_progress_page(head, page, output_published=lambda _: False)


@pytest.mark.parametrize(
    "kind",
    [
        EventType.MODEL_REQUEST_STARTED,
        EventType.MODEL_RESPONSE_DELTA,
        EventType.MODEL_RESPONSE_RECEIVED,
        EventType.PUBLIC_OUTPUT,
    ],
)
@pytest.mark.parametrize("number", [1, 4, True])
def test_old_or_unstarted_attempt_cannot_change_progress_even_for_published_output(kind, number):
    from tests.agent_storage.test_worker_progress import output_payload

    payload = (
        output_payload(attempt=number)
        if kind is EventType.PUBLIC_OUTPUT
        else {
            "attempt_number": number,
            "content_delta": "Stale text",
            "assistant_message": "Stale",
        }
    )
    head, page = head_and_page((kind, payload), state=WorkerProgressState(attempt_number=3))
    with pytest.raises(CheckpointConflict, match="Attempt"):
        fold_progress_page(head, page, output_published=lambda _: True)


def test_foreign_task_and_wrong_frontier_are_rejected():
    head, page = head_and_page((EventType.SESSION_TITLE_UPDATED, {"title": "No UI output"}))
    folded = fold_progress_page(head, page, output_published=lambda _: False)
    assert folded.head.through_sequence == 1 and folded.head.state.published_count == 0
    with pytest.raises(CheckpointConflict, match="frontier"):
        fold_progress_page(folded.head, page, output_published=lambda _: False)
    with pytest.raises(CheckpointConflict, match="another Task"):
        fold_progress_page(
            replace(head, scope=replace(head.scope, task_id=TaskId(uuid4()))),
            page,
            output_published=lambda _: False,
        )


@pytest.mark.parametrize("recovered", [False, True])
def test_live_sink_preserves_main_speech_across_tool_only_response(recovered):
    from agent_core.harness.public_output import ProgressiveEventSink

    from tests.agent_core.test_public_output import draft

    events = []
    sink = ProgressiveEventSink(
        events.append,
        user_input="Check sources",
        policy=PublicOutputPolicy(),
        recovery_state=WorkerProgressState(model_spoke=True) if recovered else None,
    )
    try:
        if not recovered:
            sink(draft(EventType.MODEL_RESPONSE_DELTA, content_delta="I will check sources."))
        sink(draft(EventType.MODEL_RESPONSE_RECEIVED, assistant_message="Tool calls proposed."))
        sink(draft(EventType.TOOL_CALL_PROPOSED, tool_call_id="read:1", tool_name="source.read"))
        assert sink._model_spoke
        assert not any(event.event_type is EventType.PUBLIC_OUTPUT for event in events)
    finally:
        sink.close()


def test_live_sink_uses_indexed_membership_and_persisted_output_budget():
    from agent_core.harness.public_output import ProgressiveEventSink

    from tests.agent_core.test_public_output import draft, verified_facts

    events, queries = [], []
    sink = ProgressiveEventSink(
        events.append,
        user_input="Check sources",
        policy=PublicOutputPolicy(max_outputs=2),
        attempt_number=2,
        recovery_state=WorkerProgressState(attempt_number=2, published_count=1),
        output_published=lambda key: key == "public:2:old",
        receipts_covered=lambda refs: queries.append(refs) or frozenset({"read:1"}),
    )
    try:
        assert not sink.publish("old", "commentary", "started", "Old")
        sink(
            draft(
                EventType.TOOL_EXECUTION_COMPLETED,
                tool_call_id="read:1",
                status="executed",
                metadata={"public_facts": verified_facts("Already reported")},
            )
        )
        assert queries == [("read:1",)] and not sink._pending
        assert sink.publish("new", "commentary", "started", "New")
        assert not sink.publish("over-budget", "status", "waiting", "Waiting")
        assert sink._published_count == 2
        outputs = [event for event in events if event.event_type is EventType.PUBLIC_OUTPUT]
        assert len(outputs) == 1 and outputs[0].payload["attempt_number"] == 2
    finally:
        sink.close()
