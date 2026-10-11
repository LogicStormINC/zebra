"""Bounded materialization and one-Event restore parity against existing replay."""

from dataclasses import replace
from datetime import UTC, datetime
from itertools import groupby
from uuid import uuid4

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
)
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import (
    ProjectionEventPlan,
    ProjectionPagePlan,
    checkpoint_version,
)
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.projection import AgUiProjector
from agent_integrations.ag_ui.task_run_binding import bind_task_run
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_integrations.coverage_public_events import strict_coverage_events

from tests.agent_integrations.test_ag_ui_projection import _golden_events

TASK = TaskId(uuid4())
A, B = SessionId(uuid4()), SessionId(uuid4())
IDENTITY = AgUiRunIdentity(session_id=A, thread_id=str(TASK), run_id="run")


class MemoryCheckpoints:
    """Test-only keyed/versioned adapter; no historical Event/body read API."""

    def __init__(self, events: tuple[TaskEvent, ...]) -> None:
        self.source = {e.task_sequence: e for e in events}
        self.heads: dict[ProjectionScope, ProjectionCheckpointHead] = {}
        self.runs: dict[ProjectionScope, TaskRunHeader] = {}
        self.headers: dict[tuple[ProjectionScope, int], ProjectionFrameHeader] = {}
        self.scalars: list[tuple[ProjectionScope, SegmentCheckpoint]] = []
        self.cells: list[tuple[ProjectionScope, ProjectionCell]] = []
        self.requests: list[tuple[int, tuple[ProjectionCellKey, ...]]] = []

    def read_checkpoint_head(self, scope: ProjectionScope) -> ProjectionCheckpointHead:
        return self.heads.get(scope, ProjectionCheckpointHead(scope))

    def _ready(self, scope: ProjectionScope, before: int) -> None:
        if before > self.read_checkpoint_head(scope).through_sequence + 1:
            raise CheckpointNotReady("not ready")

    def read_event_projection_header(
        self,
        scope: ProjectionScope,
        task_sequence: int,
    ) -> ProjectionFrameHeader | None:
        return self.headers.get((scope, task_sequence))

    def read_segment_checkpoint_before(
        self,
        scope: ProjectionScope,
        segment_id: SessionId,
        before_sequence: int,
    ) -> SegmentCheckpoint:
        self._ready(scope, before_sequence)
        rows = [
            s
            for owner, s in self.scalars
            if owner == scope and s.segment_id == segment_id and s.task_sequence < before_sequence
        ]
        return (
            max(rows, key=lambda s: s.task_sequence)
            if rows
            else SegmentCheckpoint(
                segment_id,
                -1,
                -1,
                False,
                False,
            )
        )

    def read_cells_at(
        self,
        scope: ProjectionScope,
        before_sequence: int,
        keys: tuple[ProjectionCellKey, ...],
    ) -> tuple[ProjectionCell, ...]:
        self._ready(scope, before_sequence)
        assert len(keys) <= 1_024
        self.requests.append((before_sequence, keys))
        selected: dict[ProjectionCellKey, ProjectionCell] = {}
        for owner, cell in self.cells:
            if owner == scope and cell.key in keys and cell.task_sequence < before_sequence:
                if (
                    cell.key not in selected
                    or selected[cell.key].task_sequence < cell.task_sequence
                ):
                    selected[cell.key] = cell
        return tuple(selected.values())

    def commit_projection_page(self, transition: ProjectionTransition) -> ProjectionCheckpointHead:
        head = self.read_checkpoint_head(transition.scope)
        if head.through_sequence != transition.expected_through:
            raise CheckpointConflict("lost CAS")
        predecessors: dict[SessionId, SegmentCheckpoint] = {}
        for header in transition.headers:
            entry = self.source[header.task_sequence]
            if (header.event_id, header.segment_id, header.segment_sequence) != (
                entry.event.event_id,
                entry.segment_id,
                entry.segment_sequence,
            ):
                raise CheckpointConflict("canonical identity conflict")
            if header.projected:
                prior = predecessors.get(header.segment_id) or self.read_segment_checkpoint_before(
                    transition.scope,
                    header.segment_id,
                    transition.expected_through + 1,
                )
                if prior.task_sequence != header.state_before_sequence:
                    raise CheckpointConflict("predecessor conflict")
                predecessors[header.segment_id] = next(
                    s for s in transition.scalars if s.task_sequence == header.task_sequence
                )
        latest = next((h for h in reversed(transition.headers) if h.eligible), head.latest_eligible)
        terminal = next(
            (h for h in transition.headers if h.task_sequence == transition.terminal_sequence),
            head.terminal,
        )
        updated = ProjectionCheckpointHead(
            transition.scope,
            transition.through_sequence,
            transition.headers[-1].event_id,
            latest,
            terminal,
        )
        # All validation precedes all publication; a lost CAS leaves every row untouched.
        self.headers.update(((transition.scope, h.task_sequence), h) for h in transition.headers)
        self.scalars.extend((transition.scope, s) for s in transition.scalars)
        self.cells.extend((transition.scope, c) for c in transition.cells)
        self.heads[transition.scope] = updated
        return updated


def event(
    position: int,
    kind: EventType,
    payload: dict[str, object],
    *,
    segment: SessionId = A,
    sequence: int | None = None,
) -> TaskEvent:
    source = SessionEvent(
        event_id=EventId(uuid4()),
        session_id=segment,
        sequence=position if sequence is None else sequence,
        event_type=kind,
        actor=EventActor.HARNESS,
        payload=payload,
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
    )
    return TaskEvent(TASK, position, segment, source.sequence, source)


def source_header(entry: TaskEvent) -> TaskEventHeader:
    payload = entry.event.payload
    command = payload.get("payload")
    return TaskEventHeader(
        TASK,
        entry.task_sequence,
        entry.event.event_id,
        entry.segment_id,
        entry.segment_sequence,
        entry.event.event_type,
        payload.get("kind") if isinstance(payload.get("kind"), str) else None,
        command.get("run_id") if isinstance(command, dict) else None,
    )


def plans(
    events: tuple[TaskEvent, ...],
) -> tuple[ProjectionScope, TaskRunHeader, tuple[ProjectionEventPlan, ...]]:
    # Test oracle only: production binding must use indexed metadata, never this scan.
    binding = bind_task_run(events, IDENTITY.run_id)
    run = TaskRunHeader(
        TASK,
        IDENTITY.run_id,
        len(events) - 1,
        source_header(binding.anchor) if binding.anchor is not None else None,
        binding.start,
        binding.stop,
        binding.legacy,
        binding.control_only,
        strict_coverage=strict_coverage_events(entry.event for entry in events),
    )
    scope = ProjectionScope(
        "namespace", TASK, run.anchor.event_id if run.anchor else None, checkpoint_version(run)
    )
    warm: set[int] = set()
    for _, rows in groupby(events, key=lambda e: e.segment_id):
        block = tuple(rows)
        eligible = [e for e in block if binding.includes(e)]
        if eligible:
            warm.update(
                e.task_sequence for e in block if e.task_sequence <= eligible[-1].task_sequence
            )
    decisions = tuple(
        ProjectionEventPlan(source_header(e), e.task_sequence in warm, binding.includes(e))
        for e in events
    )
    return scope, run, decisions


def materialize(
    events: tuple[TaskEvent, ...], chunk: int = 2
) -> tuple[MemoryCheckpoints, ProjectionScope]:
    port = MemoryCheckpoints(events)
    scope, run, decisions = plans(events)
    port.runs[scope] = run
    materializer = AgUiCheckpointMaterializer(port)
    for start in range(0, len(events), chunk):
        page = TaskEventPage(events[start : start + chunk], start - 1, run.highwater, 100)
        plan = ProjectionPagePlan(run, decisions[start : start + chunk])
        previous = port.read_checkpoint_head(scope)
        transition = materializer.prepare_page(page, plan, scope, IDENTITY)
        assert transition is not None
        assert port.read_checkpoint_head(scope) == previous
        port.commit_projection_page(transition)
    return port, scope


def restored(
    port: MemoryCheckpoints, scope: ProjectionScope, events: tuple[TaskEvent, ...]
) -> list[tuple[AgUiCursor, object]]:
    materializer = AgUiCheckpointMaterializer(port)
    return [
        frame
        for e in events
        if port.headers[(scope, e.task_sequence)].eligible
        for frame in materializer.iter_event_frames(scope, e, IDENTITY, run=port.runs[scope])
    ]


@pytest.mark.parametrize("chunk", [1, 2, 7, 256])
def test_golden_frames_and_every_partial_resume_match_existing_projector(chunk: int) -> None:
    events = tuple(TaskEvent(TASK, i, A, e.sequence, e) for i, e in enumerate(_golden_events(A)))
    port, scope = materialize(events, chunk)
    expected = list(AgUiTaskProjector().project_task_events(events, IDENTITY))
    assert restored(port, scope, events) == expected
    materializer = AgUiCheckpointMaterializer(port)
    for cursor, _ in expected:
        entry = events[cursor.sequence]
        actual = list(
            materializer.iter_event_frames(
                scope,
                entry,
                IDENTITY,
                run=port.runs[scope],
                after=cursor,
            )
        )
        suffix = [
            (c, f)
            for c, f in expected
            if c.sequence == cursor.sequence
            and c.frame_index is not None
            and c.frame_index > cursor.frame_index
        ]
        assert actual == suffix
        assert (
            list(
                materializer.iter_event_frames(
                    scope,
                    entry,
                    IDENTITY,
                    run=port.runs[scope],
                    after=cursor.model_copy(update={"frame_index": None}),
                )
            )
            == []
        )


def test_pre_run_prefix_is_warmed_even_when_page_ends_before_anchor() -> None:
    events = (
        event(
            0, EventType.MODEL_RESPONSE_DELTA, {"model_call_id": "old", "content_delta": "hello"}
        ),
        event(
            1,
            EventType.TOOL_CALL_PROPOSED,
            {"tool_call_id": "tool", "tool_name": "read", "arguments": {}},
        ),
        event(2, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(3, EventType.TOOL_EXECUTION_COMPLETED, {"tool_call_id": "tool", "output": "done"}),
        event(
            4,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "old", "assistant_message": "hello"},
        ),
    )
    port, scope = materialize(events, 1)
    expected = list(AgUiTaskProjector().project_task_events(events, IDENTITY))
    assert restored(port, scope, events) == expected
    assert not any(type(f).__name__ == "RunStartedEvent" for _, f in expected)
    assert not port.headers[(scope, 0)].eligible
    assert port.headers[(scope, 0)].projected


def test_revisited_segment_restores_message_and_turn_state_without_restart() -> None:
    events = (
        event(
            0, EventType.MODEL_RESPONSE_DELTA, {"model_call_id": "call", "content_delta": "hello"}
        ),
        event(
            1,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "other", "assistant_message": "b"},
            segment=B,
            sequence=0,
        ),
        event(
            2,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "call", "assistant_message": "hello"},
            sequence=1,
        ),
        event(3, EventType.TURN_COMPLETED, {}, sequence=2),
        event(4, EventType.SESSION_COMPLETED, {}, sequence=3),
    )
    port, scope = materialize(events, 1)
    assert restored(port, scope, events) == list(
        AgUiTaskProjector().project_task_events(events, IDENTITY)
    )
    assert port.headers[(scope, 2)].state_before_sequence == 0
    assert port.headers[(scope, 4)].frame_count == 0
    assert port.read_checkpoint_head(scope).terminal.task_sequence == 3


def test_silent_event_advances_source_head_and_whole_event_watermark() -> None:
    events = (
        event(0, EventType.SESSION_CREATED, {}),
        event(1, EventType.MODEL_REQUEST_STARTED, {}),
    )
    port, scope = materialize(events, 1)
    head = port.read_checkpoint_head(scope)
    assert head.through_sequence == 1 and head.latest_eligible.task_sequence == 1
    assert head.latest_eligible.frame_count == 0
    assert (
        list(
            AgUiCheckpointMaterializer(port).iter_event_frames(
                scope,
                events[1],
                IDENTITY,
                run=port.runs[scope],
            )
        )
        == []
    )


def test_tool_and_interrupt_membership_have_exact_tombstones_without_body_storage() -> None:
    events = (
        event(
            0,
            EventType.TOOL_CALL_PROPOSED,
            {"tool_call_id": "call", "tool_name": "read", "arguments": {}},
        ),
        event(1, EventType.TOOL_EXECUTION_FAILED, {"tool_call_id": "call", "output": "failed"}),
        event(
            2, EventType.APPROVAL_REQUESTED, {"tool_call_id": "approve", "reason": "secret reason"}
        ),
        event(3, EventType.APPROVAL_GRANTED, {"tool_call_id": "approve"}),
        event(
            4,
            EventType.CLARIFICATION_REQUESTED,
            {"clarification_id": "question", "question": "secret question"},
        ),
        event(5, EventType.CLARIFICATION_RESPONDED, {"clarification_id": "question"}),
    )
    port, scope = materialize(events)
    assert restored(port, scope, events) == list(
        AgUiTaskProjector().project_task_events(events, IDENTITY)
    )
    for kind, key, expected in (
        ("tool_call", "call", [(0, "1"), (1, None)]),
        ("interrupt", "approval:approve", [(2, "1"), (3, None)]),
        ("interrupt", "clarification:question", [(4, "1"), (5, None)]),
    ):
        assert [
            (c.task_sequence, c.value)
            for owner, c in port.cells
            if owner == scope and c.key.kind == kind and c.key.key == key
        ] == expected
    assert "secret" not in repr(port.cells)


def test_paired_handoff_admits_target_and_revisit_retains_original_message() -> None:
    handoff = str(uuid4())
    events = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1, EventType.MODEL_RESPONSE_DELTA, {"model_call_id": "call", "content_delta": "hello"}
        ),
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
            {"model_call_id": "other", "assistant_message": "b"},
            segment=B,
            sequence=1,
        ),
        event(
            5,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "call", "assistant_message": "hello"},
            sequence=3,
        ),
    )
    port, scope = materialize(events, 1)
    assert restored(port, scope, events) == list(
        AgUiTaskProjector().project_task_events(events, IDENTITY)
    )
    target = [
        c
        for owner, c in port.cells
        if owner == scope and c.key == ProjectionCellKey(B, "run_member", "member")
    ]
    assert [(c.task_sequence, c.value) for c in target] == [(3, "1")]


def test_lost_cas_does_not_duplicate_or_partially_publish_rows() -> None:
    events = (event(0, EventType.SESSION_CREATED, {}),)
    port = MemoryCheckpoints(events)
    scope, run, decisions = plans(events)
    transition = AgUiCheckpointMaterializer(port).prepare_page(
        TaskEventPage(events, -1, 0, 100),
        ProjectionPagePlan(run, decisions),
        scope,
        IDENTITY,
    )
    assert transition is not None
    port.commit_projection_page(transition)
    prior = (dict(port.headers), list(port.cells), list(port.scalars), dict(port.heads))
    with pytest.raises(CheckpointConflict, match="CAS"):
        port.commit_projection_page(transition)
    assert (port.headers, port.cells, port.scalars, port.heads) == prior


@pytest.mark.parametrize(
    "scope_change",
    [
        {"namespace": "foreign"},
        {"anchor_event_id": EventId(uuid4())},
        {"projector_version": "other"},
    ],
)
def test_foreign_scope_and_version_cannot_restore_state(scope_change: dict[str, object]) -> None:
    events = (event(0, EventType.SESSION_CREATED, {}),)
    port, scope = materialize(events)
    with pytest.raises(CheckpointNotReady if "namespace" in scope_change else AgUiProjectionError):
        AgUiCheckpointMaterializer(port).restore_event_frames(
            replace(scope, **scope_change),
            events[0],
            IDENTITY,
            run=port.runs[scope],
        )


def test_corrupt_source_frame_header_and_out_of_range_frame_fail_closed() -> None:
    events = (event(0, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "hi"}),)
    port, scope = materialize(events)
    materializer = AgUiCheckpointMaterializer(port)
    cursor = AgUiCursor(
        thread_id=str(TASK),
        run_id="run",
        sequence=0,
        event_id=str(events[0].event.event_id),
        frame_index=4,
    )
    with pytest.raises(AgUiProjectionError, match="outside"):
        list(
            materializer.iter_event_frames(
                scope,
                events[0],
                IDENTITY,
                run=port.runs[scope],
                after=cursor,
            )
        )
    port.headers[(scope, 0)] = replace(port.headers[(scope, 0)], event_id=EventId(uuid4()))
    with pytest.raises(CheckpointConflict, match="canonical"):
        materializer.restore_event_frames(scope, events[0], IDENTITY, run=port.runs[scope])


def test_one_event_restore_reads_only_accessed_keys_and_projects_one_body() -> None:
    events = tuple(
        event(
            i,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": f"call-{i}", "assistant_message": "hi"},
        )
        for i in range(500)
    )
    port, scope = materialize(events, 64)

    class CountingProjector(AgUiProjector):
        calls = 0

        def project_events(self, events, identity, *, state=None):
            self.calls += len(events)
            return super().project_events(events, identity, state=state)

    projector = CountingProjector()
    port.requests.clear()
    frames = AgUiCheckpointMaterializer(port, projector).restore_event_frames(
        scope,
        events[-1],
        IDENTITY,
        run=port.runs[scope],
    )
    assert frames and projector.calls == 1
    assert sum(len(keys) for _, keys in port.requests) == 3
    assert all(before == 499 for before, _ in port.requests)
