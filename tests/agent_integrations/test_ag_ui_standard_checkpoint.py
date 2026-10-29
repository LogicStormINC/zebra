"""Every frame/checkpoint boundary preserves standard identity, usage and terminals."""

from dataclasses import replace

import pytest
from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEventPage
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import ProjectionPagePlan, checkpoint_version
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.ag_ui.standard_projection import StandardAgUiProjector
from agent_integrations.ag_ui.standard_state import StandardProjectionState

from tests.agent_integrations.test_ag_ui_projection_checkpoint import (
    IDENTITY,
    A,
    B,
    MemoryCheckpoints,
    event,
    plans,
)
from tests.agent_integrations.test_ag_ui_standard_projection import VALIDATOR


def fixture():
    rows = (
        event(0, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "old", "input_tokens": 900}),
        event(1, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(2, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "m", "input_tokens": 2}),
        event(
            3,
            EventType.TOOL_CALL_PROPOSED,
            {"tool_call_id": "t", "tool_name": "shell", "arguments": {}},
        ),
        event(4, EventType.SESSION_SUSPENDED, {"reason": "waiting_children"}),
        event(
            5,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "resume", "idempotency_key": "approval-resume:test", "payload": {}},
        ),
        event(
            6,
            EventType.PUBLIC_OUTPUT,
            {
                "attempt_number": 1,
                "output_id": "p",
                "kind": "commentary",
                "phase": "work",
                "origin": "system",
                "content": "public",
            },
        ),
        event(7, EventType.TOOL_EXECUTION_COMPLETED, {"tool_call_id": "t", "output": "ok"}),
        event(8, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}),
        event(
            9,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "resume", "idempotency_key": "approval-resume:test", "payload": {}},
        ),
        event(10, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "m2", "input_tokens": 3}),
        event(11, EventType.TURN_CANCELLED, {}),
        event(12, EventType.SESSION_CANCELLED, {}),
    )
    scope, run, decisions = plans(rows)
    decisions = tuple(
        replace(d, source=replace(d.source, internal_continuation=True, command_run_id=None))
        if i in (5, 9)
        else d
        for i, d in enumerate(decisions)
    )
    profile = AgUiProjectionProfile(
        "agui-standard-1.0", projector=StandardAgUiProjector(), state_type=StandardProjectionState
    )
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    return rows, scope, run, decisions, profile


def materialize(rows, scope, run, decisions, profile, page_size):
    port = MemoryCheckpoints(rows)
    materializer = AgUiCheckpointMaterializer(port, profile=profile)
    offset = 0
    while offset < len(rows):
        batch = rows[offset : offset + page_size]
        transition = materializer.prepare_page(
            TaskEventPage(batch, offset - 1, run.highwater, 100),
            ProjectionPagePlan(run, decisions[offset : offset + page_size]),
            scope,
            IDENTITY,
        )
        assert transition is not None
        port.commit_projection_page(transition)
        offset = transition.through_sequence + 1
    frames = [
        (cursor, frame.model_dump(mode="json", by_alias=True, exclude_none=True))
        for row in rows
        if row.task_sequence >= run.start
        for cursor, frame in materializer.iter_event_frames(scope, row, IDENTITY, run=run)
    ]
    return port, materializer, frames


def test_all_page_and_frame_boundaries_equal_cold_replay():
    rows, scope, run, decisions, profile = fixture()
    _, _, expected = materialize(rows, scope, run, decisions, profile, len(rows))
    assert len([f for _, f in expected if f["type"] == "RUN_STARTED"]) == 2
    assert [f["usage"] for _, f in expected if f["type"] in {"RUN_FINISHED", "RUN_ERROR"}] == [
        [{"inputTokens": 2}],
        [{"inputTokens": 3}],
    ]
    starts = [f for _, f in expected if f["type"] == "RUN_STARTED"]
    assert starts[0]["runId"] != starts[1]["runId"]
    assert starts[1]["metadata"]["zebra"]["previousProtocolRunId"] == starts[0]["runId"]
    assert all("parentRunId" not in f for f in starts)
    for _, f in expected:
        VALIDATOR.validate(f)
    for size in range(1, len(rows)):
        _, projector, actual = materialize(rows, scope, run, decisions, profile, size)
        assert actual == expected
        for cursor, _ in actual:
            batch = rows[cursor.sequence]
            tail = [
                (c, f.model_dump(mode="json", by_alias=True, exclude_none=True))
                for c, f in projector.iter_event_frames(
                    scope, batch, IDENTITY, run=run, after=cursor
                )
            ]
            assert tail == [
                (c, f)
                for c, f in actual
                if c.sequence == cursor.sequence and c.frame_index > cursor.frame_index
            ]


def test_cross_segment_keeps_single_public_run_and_usage():
    from uuid import uuid4

    handoff = str(uuid4())
    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(1, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "a", "input_tokens": 2}),
        event(
            2,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": handoff, "target_session_id": str(B)},
        ),
        event(
            3,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": handoff, "parent_session_id": str(A)},
            segment=B,
            sequence=0,
        ),
        event(
            4,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "b", "input_tokens": 3},
            segment=B,
            sequence=1,
        ),
        event(5, EventType.TURN_COMPLETED, {}, segment=B, sequence=2),
        event(6, EventType.SESSION_COMPLETED, {}, sequence=3),
    )
    scope, run, decisions = plans(rows)
    profile = fixture()[-1]
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    expected = None
    for size in (1, 2, 256):
        port, _, frames = materialize(rows, scope, run, decisions, profile, size)
        if expected is None:
            expected = frames
        assert frames == expected
        assert len([f for _, f in frames if f["type"] == "RUN_STARTED"]) == 1
        assert len([f for _, f in frames if f["type"] == "RUN_FINISHED"]) == 1
        assert all(c.key.segment_id == A for _, c in port.cells if c.key.kind == "standard_v1")


def test_strict_native_progress_checkpoint_and_no_private_publication():
    from tests.agent_integrations.test_ag_ui_coverage_checkpoint import sources

    coverage = sources()[1:]
    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        *coverage,
    )
    scope, run, decisions = plans(rows)
    profile = fixture()[-1]
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    expected = None
    for size in (1, 2, 256):
        _, _, frames = materialize(rows, scope, run, decisions, profile, size)
        assert "PRIVATE" not in str(frames)
        progress = [
            f["value"]["accepted_units"]
            for _, f in frames
            if f.get("name") == "zebra.coverage_progress"
        ]
        assert progress == [0, 2, 4, 4]
        if expected is None:
            expected = frames
        assert frames == expected


def test_full_replay_without_any_checkpoint_equals_cold_observer():
    from agent_integrations.ag_ui.standard_binding import bind_standard, standard_header

    rows, scope, run, decisions, profile = fixture()
    state = StandardProjectionState()
    sequences = {}
    full = []
    for row, decision in zip(rows, decisions, strict=True):
        if not decision.eligible:
            continue
        identity = IDENTITY.model_copy(update={"session_id": row.segment_id})
        state.binding = None
        state.last_sequence = sequences.get(row.segment_id, -1)
        bind_standard(profile, scope, run, standard_header(row), state)
        _, frames = next(profile.projector.project_events((row.event,), identity, state=state))
        sequences[row.segment_id] = row.segment_sequence
        full.extend(
            (row.task_sequence, i, frame.model_dump(mode="json", by_alias=True, exclude_none=True))
            for i, frame in enumerate(frames)
        )
    for size in (1, 2, 256):
        _, _, cold = materialize(rows, scope, run, decisions, profile, size)
        assert [(cursor.sequence, cursor.frame_index, frame) for cursor, frame in cold] == full


def continuation_case():
    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1,
            EventType.PUBLIC_OUTPUT,
            {
                "attempt_number": 1,
                "output_id": "published",
                "kind": "commentary",
                "phase": "work",
                "origin": "system",
                "content": "public history",
            },
        ),
        event(
            2,
            EventType.PLAN_UPDATED,
            {"steps": [{"step_id": "s", "content": "work", "status": "in_progress"}]},
        ),
        event(3, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}),
        event(
            4,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "resume", "payload": {}, "idempotency_key": "approval-resume:test"},
        ),
        event(5, EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 2}),
        event(6, EventType.TURN_COMPLETED, {}),
    )
    scope, run, decisions = plans(rows)
    profile = fixture()[-1]
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    return rows, scope, run, decisions, profile


def test_continuation_snapshot_reconstructs_actual_public_document():
    args = continuation_case()
    _, _, frames = materialize(*args, 1)
    snapshots = [f["snapshot"] for _, f in frames if f["type"] == "STATE_SNAPSHOT"]
    assert snapshots == [
        {},
        {"execution": {"status": "paused", "diagnostic": "execution_storage_unavailable"}},
    ]
    assert len([f for _, f in frames if f["type"] == "ACTIVITY_SNAPSHOT"]) == 1
    assert len([f for _, f in frames if f["type"] == "TEXT_MESSAGE_CONTENT"]) == 1


def test_step_pair_retains_observed_start_across_protocol_continuation():
    rows, scope, run, decisions, profile = continuation_case()
    from datetime import timedelta

    completed = event(
        6,
        EventType.PLAN_UPDATED,
        {"steps": [{"step_id": "s", "content": "work", "status": "completed"}]},
    )
    completed = replace(
        completed,
        event=completed.event.model_copy(
            update={"created_at": rows[2].event.created_at + timedelta(minutes=2)}
        ),
    )
    terminal = event(7, EventType.TURN_COMPLETED, {})
    rows = (*rows[:6], completed, terminal)
    scope, run, decisions = plans(rows)
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    for size in (1, 256):
        _, _, frames = materialize(rows, scope, run, decisions, profile, size)
        steps = [(c, f) for c, f in frames if f["type"].startswith("STEP_")]
        assert [f["type"] for _, f in steps] == ["STEP_STARTED", "STEP_FINISHED"]
        assert [c.sequence for c, _ in steps] == [6, 6]
        assert steps[0][1]["timestamp"] == int(rows[2].event.created_at.timestamp() * 1000)
        assert steps[1][1]["timestamp"] - steps[0][1]["timestamp"] == 120_000
        assert steps[0][1]["stepName"] == steps[1][1]["stepName"]


def partial_commentary_case():
    from agent_core.harness.model_commentary import commentary_outputs, plan_response

    payload = plan_response(
        {
            "assistant_message": "public commentary " * 300,
            "model_call_id": "m",
            "attempt_number": 1,
            "response_stage": "tool_loop",
        },
        0,
    )
    chunks = commentary_outputs(payload)
    rows = [
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(1, chunks[0].event_type, chunks[0].payload),
        event(2, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}),
        event(
            3,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "resume", "payload": {}, "idempotency_key": "approval-resume:test"},
        ),
        event(4, chunks[0].event_type, chunks[0].payload),
    ]
    rows.extend(event(i + 5, chunk.event_type, chunk.payload) for i, chunk in enumerate(chunks[1:]))
    rows.append(event(len(rows), EventType.TURN_COMPLETED, {}))
    rows = tuple(rows)
    scope, run, decisions = plans(rows)
    profile = fixture()[-1]
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    return rows, scope, run, decisions, profile


def test_partial_commentary_continuation_reopens_only_real_remaining_publications():
    args = partial_commentary_case()
    expected = None
    for size in (1, 2, 256):
        _, _, frames = materialize(*args, size)
        text = [f for _, f in frames if f["type"] == "TEXT_MESSAGE_CONTENT"]
        assert "".join(f["delta"] for f in text) == "public commentary " * 300
        assert len({f["messageId"] for f in text}) == 2
        assert any(
            f.get("metadata", {}).get("zebra", {}).get("publicationComplete") is False
            for _, f in frames
            if f["type"] == "TEXT_MESSAGE_END"
        )
        if expected is None:
            expected = frames
        assert frames == expected


@pytest.mark.parametrize(
    "terminal",
    [
        EventType.TURN_COMPLETED,
        EventType.TURN_CANCELLED,
        EventType.TURN_FAILED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_CANCELLED,
        EventType.SESSION_FAILED,
    ],
)
def test_late_internal_resume_cannot_resurrect_durable_terminal(terminal):
    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(1, terminal, {}),
        event(
            2,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "resume", "payload": {}, "idempotency_key": "child-wakeup:stale"},
        ),
        event(
            3,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "late", "assistant_message": "PRIVATE", "input_tokens": 90},
        ),
    )
    scope, run, decisions = plans(rows)
    profile = fixture()[-1]
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    for size in (1, 256):
        _, _, frames = materialize(rows, scope, run, decisions, profile, size)
        assert len([f for _, f in frames if f["type"] == "RUN_STARTED"]) == 1
        assert not any(c.sequence >= 2 for c, _ in frames)
        assert "PRIVATE" not in str(frames)


@pytest.mark.parametrize(
    "terminal",
    [
        EventType.TURN_COMPLETED,
        EventType.TURN_CANCELLED,
        EventType.TURN_FAILED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_CANCELLED,
        EventType.SESSION_FAILED,
    ],
)
def test_terminal_after_already_closed_pause_still_blocks_late_resume(terminal):
    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(1, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}),
        event(2, terminal, {}),
        event(
            3,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "resume", "payload": {}, "idempotency_key": "child-wakeup:stale"},
        ),
    )
    scope, run, decisions = plans(rows)
    profile = fixture()[-1]
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    _, _, frames = materialize(rows, scope, run, decisions, profile, 1)
    assert len([f for _, f in frames if f["type"] == "RUN_STARTED"]) == 1
    assert not any(c.sequence >= 2 for c, _ in frames)


@pytest.mark.parametrize(
    "corruption",
    [
        "count_missing",
        "version",
        "private_execution_key",
        "wrong_protocol",
        "not_started",
        "unknown_root_key",
    ],
)
def test_corrupt_required_root_state_never_silently_restarts_or_loses_usage(corruption):
    import json

    from agent_core.ports.task_projection_checkpoints import ProjectionCell
    from agent_integrations.ag_ui.contracts import AgUiProjectionError

    rows, scope, run, decisions, profile = fixture()
    port = MemoryCheckpoints(rows)
    materializer = AgUiCheckpointMaterializer(port, profile=profile)
    transition = materializer.prepare_page(
        TaskEventPage(rows[:3], -1, run.highwater, 100),
        ProjectionPagePlan(run, decisions[:3]),
        scope,
        IDENTITY,
    )
    port.commit_projection_page(transition)
    if corruption == "count_missing":
        port.cells = [
            (s, c)
            for s, c in port.cells
            if not (c.key.kind == "standard_v1" and c.key.key == "count")
        ]
    else:
        row = max(
            (c for s, c in port.cells if c.key.kind == "standard_v1" and c.key.key == "0"),
            key=lambda c: c.task_sequence,
        )
        data = json.loads(row.value)
        if corruption == "version":
            data["version"] = 2
        elif corruption == "private_execution_key":
            data["public_execution"] = {"secret": "PRIVATE"}
        elif corruption == "wrong_protocol":
            data["protocol_run_id"] = "agui:" + "f" * 64
        elif corruption == "not_started":
            data["started"] = False
        else:
            data["raw_payload"] = "PRIVATE"
        bad = ProjectionCell(row.key, row.task_sequence, json.dumps(data))
        port.cells = [(s, bad if c is row else c) for s, c in port.cells]
    with pytest.raises(AgUiProjectionError):
        materializer.prepare_page(
            TaskEventPage(rows[3:4], 2, run.highwater, 100),
            ProjectionPagePlan(run, decisions[3:4]),
            scope,
            IDENTITY,
        )
    assert port.read_checkpoint_head(scope).through_sequence == 2


def test_inflight_child_unknown_usage_survives_slices_and_resets_only_after_settlement():
    from hashlib import sha256

    from tests.agent_integrations.test_ag_ui_projection_checkpoint import TASK

    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(1, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "p1", "input_tokens": 1}),
        event(
            2,
            EventType.SUBAGENT_DELEGATED,
            {"child_task_id": "child", "tool_call_id": "c", "tool_name": "agent"},
        ),
        event(3, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}),
        event(
            4,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "resume", "payload": {}, "idempotency_key": "approval-resume:one"},
        ),
        event(5, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "p2", "input_tokens": 2}),
        event(
            6,
            EventType.SESSION_COMMAND_ACCEPTED,
            {
                "kind": "resume",
                "expected_revision": 2,
                "idempotency_key": f"child-wakeup:{TASK}:" + sha256(b"child").hexdigest(),
                "payload": {"child_results": [{"child_task_id": "child", "status": "completed"}]},
            },
        ),
        event(7, EventType.SESSION_SUSPENDED, {"reason": "execution_storage_unavailable"}),
        event(
            8,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "resume", "payload": {}, "idempotency_key": "approval-resume:two"},
        ),
        event(9, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "p3", "input_tokens": 3}),
        event(10, EventType.TURN_COMPLETED, {}),
    )
    scope, run, decisions = plans(rows)
    profile = fixture()[-1]
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    for size in (1, 256):
        _, _, frames = materialize(rows, scope, run, decisions, profile, size)
        terminals = [f for _, f in frames if f["type"] in {"RUN_ERROR", "RUN_FINISHED"}]
        assert len(terminals) == 3
        assert all("usage" not in f for f in terminals[:2])
        assert terminals[2]["usage"] == [{"inputTokens": 3}]


def test_full_256_source_page_advances_bounded_prefix_without_skipping_or_resetting():
    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        *(
            event(
                i,
                EventType.MODEL_RESPONSE_RECEIVED,
                {"model_call_id": f"call-{i}", "input_tokens": 1},
            )
            for i in range(1, 257)
        ),
        event(257, EventType.TURN_COMPLETED, {}),
    )
    scope, run, decisions = plans(rows)
    profile = fixture()[-1]
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    port, _, frames = materialize(rows, scope, run, decisions, profile, 256)
    assert port.read_checkpoint_head(scope).through_sequence == 257
    assert len([f for _, f in frames if f["type"] == "RUN_STARTED"]) == 1
    assert len([f for _, f in frames if f.get("name") == "zebra.model_usage.v1"]) == 256
    terminal = next(f for _, f in frames if f["type"] == "RUN_FINISHED")
    assert terminal["usage"] == [{"inputTokens": 256}]
