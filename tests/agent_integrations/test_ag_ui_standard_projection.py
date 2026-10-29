"""Public facts, complete arguments and real lifecycle semantics for the new profile."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.standard_projection import StandardAgUiProjector
from agent_integrations.ag_ui.standard_state import StandardProjectionState
from jsonschema import Draft202012Validator

SCHEMA = json.loads(
    (Path(__file__).parents[1] / "conformance/agui_contract/schema-1.0.json").read_text()
)
VALIDATOR = Draft202012Validator({"$ref": "#/$defs/Event", "$defs": SCHEMA["$defs"]})


def source(sequence, kind, payload, session):
    return SessionEvent(
        event_id=uuid4(),
        session_id=session,
        sequence=sequence,
        event_type=kind,
        payload=payload,
        actor=EventActor.HARNESS,
        created_at=datetime(2026, 10, 29, tzinfo=UTC),
    )


def project(specs, *, strict=False):
    session = uuid4()
    identity = AgUiRunIdentity(session_id=session, thread_id="task", run_id="public-run")
    events = tuple(source(i, kind, payload, session) for i, (kind, payload) in enumerate(specs))
    state = StandardProjectionState()
    result = list(
        StandardAgUiProjector().project_events(
            events, identity, state=state, strict_coverage=strict
        )
    )
    frames = [
        frame.model_dump(mode="json", by_alias=True, exclude_none=True)
        for _, batch in result
        for frame in batch
    ]
    for frame in frames:
        VALIDATOR.validate(frame)
    return frames, state


def test_proposal_closes_arguments_and_execution_is_separate():
    frames, _ = project(
        [
            (
                EventType.TOOL_CALL_PROPOSED,
                {"tool_call_id": "t", "tool_name": "shell", "arguments": {}},
            ),
            (EventType.TOOL_EXECUTION_STARTED, {"tool_call_id": "t", "tool_name": "shell"}),
            (EventType.TOOL_EXECUTION_COMPLETED, {"tool_call_id": "t", "output": "ok"}),
            (EventType.TURN_COMPLETED, {}),
            (EventType.SESSION_COMPLETED, {}),
        ]
    )
    assert [f["type"] for f in frames if f["type"] != "STATE_SNAPSHOT"][:4] == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
    ]
    assert len([f for f in frames if f["type"] == "TOOL_CALL_END"]) == 1
    assert [f["content"]["status"] for f in frames if f["type"] == "ACTIVITY_SNAPSHOT"] == [
        "running",
        "completed",
    ]
    assert len([f for f in frames if f["type"] == "RUN_FINISHED"]) == 1


def test_candidate_private_and_commentary_reservation_never_publish():
    frames, _ = project(
        [
            (EventType.MODEL_RESPONSE_DELTA, {"content_delta": "secret", "model_call_id": "m"}),
            (
                EventType.MODEL_RESPONSE_RECEIVED,
                {
                    "model_call_id": "m",
                    "assistant_message": "secret",
                    "response_stage": "candidate",
                    "public_commentary": {"disposition": "admitted"},
                },
            ),
            (
                EventType.ANSWER_COMMITTED,
                {
                    "assistant_message": "public",
                    "delivery_assessment": {"status": "partial"},
                },
            ),
        ]
    )
    assert "secret" not in json.dumps(frames)
    assert [f["delta"] for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT"] == ["public"]


def test_cancellation_once_and_no_fake_tool_result():
    frames, _ = project(
        [
            (
                EventType.TOOL_CALL_PROPOSED,
                {"tool_call_id": "t", "tool_name": "shell", "arguments": {}},
            ),
            (EventType.TURN_CANCELLED, {}),
            (EventType.SESSION_CANCELLED, {}),
        ]
    )
    assert [f["outcome"] for f in frames if f["type"] == "RUN_FINISHED"] == [{"type": "cancelled"}]
    assert not any(f["type"] == "TOOL_CALL_RESULT" for f in frames)


def test_plan_only_observed_matching_terminal_closes_step():
    def plan(status, step="s"):
        return {"steps": [{"step_id": step, "content": "real step", "status": status}]}

    frames, _ = project(
        [
            (EventType.PLAN_UPDATED, plan("in_progress")),
            (EventType.PLAN_UPDATED, plan("completed")),
            (EventType.PLAN_UPDATED, plan("completed", "unseen")),
        ]
    )
    assert [f["type"] for f in frames if f["type"].startswith("STEP_")] == [
        "STEP_STARTED",
        "STEP_FINISHED",
    ]
    frames, _ = project(
        [
            (EventType.PLAN_UPDATED, plan("in_progress")),
            (EventType.PLAN_UPDATED, {"steps": []}),
            (EventType.TURN_COMPLETED, {}),
        ]
    )
    assert not any(f["type"].startswith("STEP_") for f in frames)


def test_usage_counts_call_once_and_cache_miss_is_not_cache_write():
    payload = {
        "model_call_id": "m",
        "input_tokens": 10,
        "output_tokens": 4,
        "prompt_cache_hit_tokens": 3,
        "prompt_cache_miss_tokens": 7,
        "reasoning_tokens": 2,
    }
    frames, _ = project(
        [
            (EventType.MODEL_RESPONSE_RECEIVED, payload),
            (EventType.MODEL_RESPONSE_RECEIVED, payload),
            (EventType.TURN_COMPLETED, {}),
        ]
    )
    usage = next(f["usage"] for f in frames if f["type"] == "RUN_FINISHED")
    assert usage == [
        {
            "inputTokens": 10,
            "outputTokens": 4,
            "totalTokens": 14,
            "reasoningTokens": 2,
            "cachedInputTokens": 3,
        }
    ]
    with pytest.raises(ValueError):
        project([(EventType.MODEL_RESPONSE_RECEIVED, {**payload, "input_tokens": True})])


def test_strict_coverage_sanitizes_before_projection():
    frames, _ = project(
        [
            (EventType.ANSWER_COMMITTED, {"assistant_message": "secret"}),
            (EventType.TURN_FAILED, {"reason": "secret"}),
        ],
        strict=True,
    )
    assert "secret" not in json.dumps(frames)
    assert not any(f["type"] == "TEXT_MESSAGE_CONTENT" for f in frames)


def test_official_schema_rejects_invalid_event_shapes():
    for frame in [
        {"type": "TEXT_MESSAGE_START", "messageId": "m", "role": "private"},
        {"type": "RUN_FINISHED", "threadId": "t", "runId": "r", "outcome": {"type": "pretend"}},
        {
            "type": "ACTIVITY_DELTA",
            "messageId": "m",
            "activityType": "plan",
            "patch": [{"op": "replace", "path": "/x"}],
        },
    ]:
        assert list(VALIDATOR.iter_errors(frame))


def test_child_terminal_requires_canonical_current_harness_epoch():
    from hashlib import sha256

    from agent_integrations.ag_ui.standard_subagents import subagent_events

    session = uuid4()
    state = StandardProjectionState()
    delegated = source(
        1,
        EventType.SUBAGENT_DELEGATED,
        {"child_task_id": "child", "tool_call_id": "call", "tool_name": "agent"},
        session,
    )
    start = subagent_events(delegated, state, "task")
    assert len(start) == 1
    VALIDATOR.validate(start[0].model_dump(mode="json", by_alias=True, exclude_none=True))
    digest = sha256(b"child").hexdigest()
    payload = {
        "kind": "resume",
        "expected_revision": 1,
        "idempotency_key": "child-wakeup:task:" + digest,
        "payload": {
            "child_results": [
                {"child_task_id": "child", "status": "completed", "summary": "PRIVATE"}
            ]
        },
    }
    wakeup = source(2, EventType.SESSION_COMMAND_ACCEPTED, payload, session)
    forged = wakeup.model_copy(update={"actor": EventActor.USER})
    assert subagent_events(forged, state, "task") == ()
    for results in [
        [],
        [{"child_task_id": "other", "status": "completed"}],
        [{"child_task_id": "child", "status": "unknown"}],
        payload["payload"]["child_results"] * 2,
    ]:
        invalid = wakeup.model_copy(
            update={"payload": {**payload, "payload": {"child_results": results}}}
        )
        assert subagent_events(invalid, state, "task") == ()
    assert (
        subagent_events(
            wakeup.model_copy(update={"payload": {**payload, "expected_revision": 0}}),
            state,
            "task",
        )
        == ()
    )
    result = subagent_events(wakeup, state, "task")
    assert [f.type.value for f in result] == ["SUBAGENT_STARTED", "SUBAGENT_FINISHED"]
    assert result[0].subagent_run_id == start[0].content["invocation_id"]
    assert "PRIVATE" not in str(result)
    assert subagent_events(wakeup, state, "task") == ()


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_child_error_and_cancellation_are_not_success(status):
    from hashlib import sha256

    from agent_integrations.ag_ui.standard_subagents import subagent_events

    session, state = uuid4(), StandardProjectionState()
    subagent_events(
        source(
            1,
            EventType.SUBAGENT_DELEGATED,
            {"child_task_id": "child", "tool_call_id": "call", "tool_name": "agent"},
            session,
        ),
        state,
        "task",
    )
    wakeup = source(
        2,
        EventType.SESSION_COMMAND_ACCEPTED,
        {
            "kind": "resume",
            "expected_revision": 1,
            "idempotency_key": "child-wakeup:task:" + sha256(b"child").hexdigest(),
            "payload": {"child_results": [{"child_task_id": "child", "status": status}]},
        },
        session,
    )
    frames = subagent_events(wakeup, state, "task")
    assert len(frames) == 2 and frames[1].type.value == "SUBAGENT_ERROR"
    VALIDATOR.validate(frames[0].model_dump(mode="json", by_alias=True, exclude_none=True))


def test_actual_research_producer_carries_exact_invocation_attribution():
    from types import SimpleNamespace

    from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
    from agent_core.harness.tool_execution import _subagent_lifecycle_events
    from agent_integrations.ag_ui.standard_subagents import subagent_events

    call = ToolCall(
        tool_call_id=uuid4(), name="agent.research", arguments={}, created_at=datetime.now(UTC)
    )
    result = ToolResult(
        tool_call_id=call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="PRIVATE",
        metadata={
            "subagent_id": "invocation",
            "subagent_status": "completed",
            "provenance": "PRIVATE",
            "max_model_calls": 1,
            "max_tool_calls": 1,
            "max_depth": 1,
        },
    )
    drafts = _subagent_lifecycle_events(
        SimpleNamespace(attempt=SimpleNamespace(number=1)), tool_call=call, tool_result=result
    )
    assert all(d.payload["tool_call_id"] == str(call.tool_call_id) for d in drafts)
    session, state = uuid4(), StandardProjectionState()
    projected = [
        f
        for i, draft in enumerate(drafts)
        for f in subagent_events(source(i, draft.event_type, draft.payload, session), state, "task")
    ]
    assert [f.type.value for f in projected] == ["SUBAGENT_STARTED", "SUBAGENT_FINISHED"]
    assert projected[0].parent_tool_call_id == str(call.tool_call_id)
    assert projected[0].subagent_run_id == projected[1].subagent_run_id
    assert "PRIVATE" not in str(projected)
    for frame in projected:
        VALIDATOR.validate(frame.model_dump(mode="json", by_alias=True, exclude_none=True))


def test_actual_commentary_publications_join_only_durable_chunks():
    from agent_core.harness.model_commentary import commentary_outputs, plan_response

    text = "public commentary " * 300
    payload = plan_response(
        {
            "assistant_message": text,
            "model_call_id": "m",
            "attempt_number": 1,
            "response_stage": "tool_loop",
        },
        0,
    )
    drafts = commentary_outputs(payload)
    assert len(drafts) > 1
    specs = [(EventType.MODEL_RESPONSE_RECEIVED, payload)]
    specs.extend((d.event_type, d.payload) for d in drafts)
    frames, _ = project(specs)
    assert len([f for f in frames if f["type"] == "TEXT_MESSAGE_START"]) == 1
    assert len([f for f in frames if f["type"] == "TEXT_MESSAGE_END"]) == 1
    assert "".join(f["delta"] for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT") == text
    assert len({f["messageId"] for f in frames if f["type"].startswith("TEXT_MESSAGE_")}) == 1


def test_replacing_active_step_content_does_not_manufacture_success():
    frames, _ = project(
        [
            (
                EventType.PLAN_UPDATED,
                {"steps": [{"step_id": "s", "content": "original", "status": "in_progress"}]},
            ),
            (
                EventType.PLAN_UPDATED,
                {"steps": [{"step_id": "s", "content": "replacement", "status": "completed"}]},
            ),
        ]
    )
    assert not any(f["type"].startswith("STEP_") for f in frames)


@pytest.mark.parametrize(
    "reason,status",
    [("delivery_requirements_unmet", "blocked"), ("verification_required", "partial")],
)
def test_delivery_pause_is_assessment_and_cancelled_without_fake_interrupt(reason, status):
    frames, _ = project(
        [
            (EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "m", "input_tokens": 2}),
            (
                EventType.SESSION_SUSPENDED,
                {
                    "reason": reason,
                    "metadata": {
                        "delivery_assessment": {
                            "status": status,
                            "goal": "public goal",
                            "unmet": ["verification"],
                            "evidence_refs": ["receipt:1"],
                            "artifact_refs": ["artifact:1"],
                        },
                        "snapshot_path": "PRIVATE",
                    },
                },
            ),
        ]
    )
    assert not any("interrupt" in json.dumps(f).lower() for f in frames)
    assert "PRIVATE" not in str(frames)
    terminal = [f for f in frames if f["type"] == "RUN_FINISHED"]
    assert len(terminal) == 1 and terminal[0]["outcome"] == {"type": "cancelled"}
    assert terminal[0]["usage"] == [{"inputTokens": 2}]
    assert any(f.get("value", {}).get("status") == status for f in frames)
    assessment = next(f["value"] for f in frames if f.get("name") == "zebra.delivery_assessment.v1")
    assert assessment["unmet"] == ["verification"]
    assert assessment["evidence_refs"] == ["receipt:1"]
    assert assessment["artifact_refs"] == ["artifact:1"]


@pytest.mark.parametrize(
    "payload",
    [
        {"reason": "execution_storage_unavailable"},
        {"reason": "plugin_authority_unavailable"},
        {"snapshot_path": "/PRIVATE", "runtime": "PRIVATE"},
        {"reason": "arbitrary PRIVATE"},
    ],
)
def test_operational_pause_is_public_state_without_fake_terminal_or_private_metadata(payload):
    frames, _ = project([(EventType.SESSION_SUSPENDED, payload)])
    assert "PRIVATE" not in str(frames)
    expected = (
        "RUN_ERROR"
        if payload.get("reason")
        in {"execution_storage_unavailable", "plugin_authority_unavailable"}
        else "RUN_FINISHED"
    )
    terminal = [f for f in frames if f["type"] in {"RUN_ERROR", "RUN_FINISHED"}]
    assert len(terminal) == 1 and terminal[0]["type"] == expected
    assert not any(f["type"] == "MESSAGES_SNAPSHOT" for f in frames)
    delta = next(f["delta"] for f in frames if f["type"] == "STATE_DELTA")
    assert delta[0]["op"] == "add" and delta[0]["path"] == "/execution"
    assert delta[0]["value"]["status"] == "paused"


def test_clarification_preserves_state_and_history_with_correct_tool_identity():
    frames, _ = project(
        [
            (
                EventType.PLAN_UPDATED,
                {"steps": [{"step_id": "s", "content": "work", "status": "in_progress"}]},
            ),
            (EventType.ANSWER_COMMITTED, {"assistant_message": "existing public answer"}),
            (
                EventType.CLARIFICATION_REQUESTED,
                {
                    "clarification_id": "question",
                    "question": "Which?",
                    "response_schema": {"type": "string"},
                },
            ),
        ]
    )
    assert not any(f["type"] in {"STATE_SNAPSHOT", "MESSAGES_SNAPSHOT"} for f in frames[2:])
    terminal = next(f for f in frames if f["type"] == "RUN_FINISHED")
    interrupt = terminal["outcome"]["interrupts"][0]
    assert interrupt["id"] == "clarification:question" and "toolCallId" not in interrupt
    assert interrupt["responseSchema"] == {"type": "string"}


def test_wholly_unknown_call_invalidates_whole_run_total_but_retains_call_facts():
    frames, _ = project(
        [
            (EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "unknown"}),
            (EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "total", "total_tokens": 5}),
            (EventType.TURN_FAILED, {"reason": "PRIVATE"}),
            (EventType.SESSION_FAILED, {}),
        ]
    )
    terminal = [f for f in frames if f["type"] == "RUN_ERROR"]
    assert len(terminal) == 1 and "usage" not in terminal[0]
    fact = next(f["value"] for f in frames if f.get("name") == "zebra.model_usage.v1")
    assert fact["scope"] == "model_call" and fact["usage"] == {"totalTokens": 5}
    assert "PRIVATE" not in str(frames)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_complete_tool_arguments_require_strict_json_even_for_pure_projection(number):
    with pytest.raises(ValueError, match="JSON serializable"):
        project(
            [
                (
                    EventType.TOOL_CALL_PROPOSED,
                    {"tool_call_id": "t", "tool_name": "shell", "arguments": {"invalid": number}},
                )
            ]
        )


def test_partial_published_commentary_closes_without_fabricating_missing_text():
    from agent_core.harness.model_commentary import commentary_outputs, plan_response

    payload = plan_response(
        {
            "assistant_message": "public " * 700,
            "model_call_id": "m",
            "attempt_number": 1,
            "response_stage": "tool_loop",
        },
        0,
    )
    first = commentary_outputs(payload)[0]
    frames, _ = project([(first.event_type, first.payload), (EventType.TURN_CANCELLED, {})])
    assert (
        "".join(f["delta"] for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT")
        == first.payload["content"]
    )
    end = next(f for f in frames if f["type"] == "TEXT_MESSAGE_END")
    assert end["metadata"]["zebra"]["publicationComplete"] is False
    assert [f["type"] for f in frames[-2:]] == ["TEXT_MESSAGE_END", "RUN_FINISHED"]


@pytest.mark.parametrize("terminal", [EventType.TURN_CANCELLED, EventType.APPROVAL_REQUESTED])
def test_pending_delegation_has_activity_and_no_orphan_or_fake_child_terminal(terminal):
    frames, _ = project(
        [
            (
                EventType.SUBAGENT_DELEGATED,
                {"child_task_id": "child", "tool_call_id": "call", "tool_name": "agent"},
            ),
            (terminal, {"tool_call_id": "approval", "reason": "approval"}),
        ]
    )
    assert not any(f["type"].startswith("SUBAGENT_") for f in frames)
    assert any(f.get("content", {}).get("status") == "delegated" for f in frames)
    assert len([f for f in frames if f["type"] == "RUN_FINISHED"]) == 1


def test_workspace_drift_is_public_paused_state_not_execution_failure():
    frames, _ = project(
        [
            (
                EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED,
                {"snapshot_path": "/PRIVATE", "reason": "PRIVATE"},
            )
        ]
    )
    assert not any(f["type"] == "RUN_ERROR" for f in frames)
    patch = next(f["delta"][0]["value"] for f in frames if f["type"] == "STATE_DELTA")
    assert patch == {"status": "paused", "diagnostic": "workspace_changed"}
    assert "PRIVATE" not in str(frames)


def test_standard_producer_declares_its_own_protocol_version():
    frames, _ = project([(EventType.TURN_COMPLETED, {})])
    assert frames[0]["protocolVersion"] == "1.0"


def test_unknown_call_in_known_model_group_invalidates_all_its_aggregate_fields():
    frames, _ = project(
        [
            (
                EventType.MODEL_RESPONSE_RECEIVED,
                {
                    "model_call_id": "known",
                    "provider": "p",
                    "resolved_model": "m",
                    "input_tokens": 8,
                    "output_tokens": 2,
                },
            ),
            (
                EventType.MODEL_RESPONSE_RECEIVED,
                {"model_call_id": "unknown", "provider": "p", "resolved_model": "m"},
            ),
            (EventType.TURN_COMPLETED, {}),
        ]
    )
    terminal = next(f for f in frames if f["type"] == "RUN_FINISHED")
    assert all(not any(k.endswith("Tokens") for k in row) for row in terminal.get("usage", []))


@pytest.mark.parametrize(
    "work",
    [
        [
            (
                EventType.SUBAGENT_DELEGATED,
                {"child_task_id": "child", "tool_call_id": "c", "tool_name": "agent"},
            )
        ],
        [
            (
                EventType.SUBAGENT_STARTED,
                {"subagent_id": "research", "tool_call_id": "c", "tool_name": "agent.research"},
            )
        ],
        [
            (
                EventType.TOOL_CALL_PROPOSED,
                {"tool_call_id": "c", "tool_name": "agent.research", "arguments": {}},
            ),
            (EventType.TOOL_EXECUTION_STARTED, {"tool_call_id": "c"}),
        ],
    ],
)
def test_unreported_child_tokens_never_masquerade_as_inclusive_terminal_usage(work):
    frames, _ = project(
        [
            (EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "parent", "input_tokens": 5}),
            *work,
            (EventType.TURN_CANCELLED, {}),
        ]
    )
    terminal = next(f for f in frames if f["type"] == "RUN_FINISHED")
    assert "usage" not in terminal
    fact = next(f["value"] for f in frames if f.get("name") == "zebra.model_usage.v1")
    assert fact["scope"] == "model_call" and fact["usage"] == {"inputTokens": 5}


@pytest.mark.parametrize(
    "kind,payload,terminal",
    [
        (EventType.SESSION_SUSPENDED, {"reason": "waiting_children"}, None),
        (EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}, "RUN_ERROR"),
        (EventType.SESSION_SUSPENDED, {"reason": "execution_authority_unavailable"}, "RUN_ERROR"),
        (EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED, {}, "RUN_FINISHED"),
    ],
)
def test_strict_lifecycle_preserves_only_safe_classification(kind, payload, terminal):
    for strict in (False, True):
        frames, _ = project(
            [
                (
                    kind,
                    {
                        **payload,
                        "metadata": {"snapshot_path": "PRIVATE"},
                        "assistant_message": "PRIVATE",
                    },
                )
            ],
            strict=strict,
        )
        actual = [f["type"] for f in frames if f["type"] in {"RUN_ERROR", "RUN_FINISHED"}]
        assert actual == ([] if terminal is None else [terminal])
        assert "PRIVATE" not in str(frames)
