"""Adversarial run isolation, pre-admission bounds and causal handoff proofs."""

from dataclasses import replace
from uuid import uuid4

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCell,
    ProjectionCellKey,
)
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import ProjectionHandoffProof, ProjectionPagePlan
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiProjectionError
from agent_integrations.ag_ui.projection import AgUiProjector
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector

from tests.agent_integrations.test_ag_ui_projection_checkpoint import (
    IDENTITY,
    A,
    B,
    MemoryCheckpoints,
    event,
    materialize,
    plans,
    restored,
    source_header,
)


class CountingProjector(AgUiProjector):
    def __init__(self) -> None:
        self.calls = 0

    def project_events(self, events, identity, *, state=None):
        self.calls += len(events)
        return super().project_events(events, identity, state=state)


def test_restore_and_whole_event_cursor_reject_another_run_without_projection() -> None:
    events = (event(0, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "hello"}),)
    port, scope = materialize(events)
    spy = CountingProjector()
    materializer = AgUiCheckpointMaterializer(port, spy)
    foreign = IDENTITY.model_copy(update={"run_id": "foreign"})
    with pytest.raises(AgUiProjectionError, match="bound Task/run"):
        materializer.restore_event_frames(scope, events[0], foreign, run=port.runs[scope])
    cursor = AgUiCursor(
        thread_id=foreign.thread_id,
        run_id=foreign.run_id,
        sequence=0,
        event_id=str(events[0].event.event_id),
    )
    with pytest.raises(AgUiProjectionError, match="bound Task/run"):
        list(
            materializer.iter_event_frames(
                scope, events[0], foreign, run=port.runs[scope], after=cursor
            )
        )
    assert spy.calls == 0


@pytest.mark.parametrize("field,value", [("control_only", True), ("highwater", -1)])
def test_restore_rejects_control_only_or_outside_snapshot(field: str, value: object) -> None:
    events = (event(0, EventType.SESSION_CREATED, {}),)
    port, scope = materialize(events)
    with pytest.raises(AgUiProjectionError, match="window"):
        AgUiCheckpointMaterializer(port).restore_event_frames(
            scope,
            events[0],
            IDENTITY,
            run=replace(port.runs[scope], **{field: value}),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"assistant_message": "x" * 1_048_577},
        {"assistant_message": "hello", "bad": float("nan")},
        {"assistant_message": "hello", "bad": list(range(65_537))},
    ],
)
def test_bad_source_fails_before_projection_or_any_publication(payload: dict[str, object]) -> None:
    events = (event(0, EventType.MODEL_RESPONSE_RECEIVED, payload),)
    port = MemoryCheckpoints(events)
    scope, run, decisions = plans(events)
    spy = CountingProjector()
    with pytest.raises(AgUiProjectionError):
        AgUiCheckpointMaterializer(port, spy).prepare_page(
            TaskEventPage(events, -1, 0, 100),
            ProjectionPagePlan(run, decisions),
            scope,
            IDENTITY,
        )
    assert spy.calls == 0
    assert port.read_checkpoint_head(scope).through_sequence == -1
    assert not port.cells and not port.headers and not port.scalars


def test_cyclic_source_is_rejected_by_bounded_depth_before_json_encoder() -> None:
    payload: dict[str, object] = {"assistant_message": "hello"}
    payload["cycle"] = payload
    events = (event(0, EventType.MODEL_RESPONSE_RECEIVED, payload),)
    port = MemoryCheckpoints(events)
    scope, run, decisions = plans(events)
    spy = CountingProjector()
    with pytest.raises(AgUiProjectionError, match="depth"):
        AgUiCheckpointMaterializer(port, spy).prepare_page(
            TaskEventPage(events, -1, 0, 100),
            ProjectionPagePlan(run, decisions),
            scope,
            IDENTITY,
        )
    assert spy.calls == 0


@pytest.mark.parametrize(
    "count,identifier", [(4_096, "child"), (520, "x" * 1_900)], ids=["frame-count", "frame-bytes"]
)
def test_variable_fanout_is_admitted_before_bulk_frame_construction(
    count: int, identifier: str
) -> None:
    events = (
        event(
            0,
            EventType.SESSION_COMMAND_ACCEPTED,
            {
                "kind": "run",
                "payload": {
                    "run_id": "run",
                    "child_results": [
                        {"child_task_id": identifier, "status": "completed"} for _ in range(count)
                    ],
                },
            },
        ),
    )
    scope, run, decisions = plans(events)
    port, spy = MemoryCheckpoints(events), CountingProjector()
    with pytest.raises(AgUiProjectionError, match="before projection"):
        AgUiCheckpointMaterializer(port, spy).prepare_page(
            TaskEventPage(events, -1, 0, 100),
            ProjectionPagePlan(run, decisions),
            scope,
            IDENTITY,
        )
    assert spy.calls == 0 and not port.headers


def test_exact_frame_limit_is_not_weakened_by_conservative_counting() -> None:
    events = (
        event(
            0,
            EventType.SESSION_COMMAND_ACCEPTED,
            {
                "kind": "run",
                "payload": {
                    "run_id": "run",
                    "child_results": [
                        {"child_task_id": "child", "status": "completed"} for _ in range(4_095)
                    ],
                },
            },
        ),
    )
    port, scope = materialize(events)
    assert port.headers[(scope, 0)].frame_count == 4_096
    assert restored(port, scope, events) == list(
        AgUiTaskProjector().project_task_events(events, IDENTITY)
    )


def _materialize_with_proofs(
    events: tuple[TaskEvent, ...],
    proofs: tuple[ProjectionHandoffProof, ...],
    chunk: int,
) -> tuple[MemoryCheckpoints, object]:
    port = MemoryCheckpoints(events)
    scope, run, decisions = plans(events)
    port.runs[scope] = run
    materializer = AgUiCheckpointMaterializer(port)
    for start in range(0, len(events), chunk):
        transition = materializer.prepare_page(
            TaskEventPage(events[start : start + chunk], start - 1, run.highwater, 100),
            ProjectionPagePlan(run, decisions[start : start + chunk], proofs),
            scope,
            IDENTITY,
        )
        assert transition is not None
        port.commit_projection_page(transition)
        # Lookahead may select frames, but may never publish a future membership version.
        assert all(
            cell.task_sequence <= port.read_checkpoint_head(scope).through_sequence
            for _, cell in port.cells
        )
    return port, scope


@pytest.mark.parametrize("chunk", [1, 64, 256])
def test_future_handoff_preserves_long_prefix_warming_across_pages(chunk: int) -> None:
    handoff = uuid4()
    prefix = tuple(
        event(
            i + 2,
            EventType.MODEL_RESPONSE_DELTA,
            {"model_call_id": "call", "content_delta": "x"},
            segment=B,
            sequence=i,
        )
        for i in range(300)
    )
    events = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(B)},
        ),
        *prefix,
        event(
            302,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(A)},
            segment=B,
            sequence=300,
        ),
        event(
            303,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "call", "assistant_message": "x" * 300},
            segment=B,
            sequence=301,
        ),
    )
    proof = ProjectionHandoffProof(handoff, source_header(events[1]), source_header(events[302]))
    port, scope = _materialize_with_proofs(events, (proof,), chunk)
    assert restored(port, scope, events) == list(
        AgUiTaskProjector().project_task_events(events, IDENTITY)
    )
    members = [
        cell for _, cell in port.cells if cell.key == ProjectionCellKey(B, "run_member", "member")
    ]
    assert [(cell.task_sequence, cell.value) for cell in members] == [(302, "1")]


def test_future_membership_cannot_authorize_earlier_commit_in_the_same_page() -> None:
    c = SessionId(uuid4())
    first, second = uuid4(), uuid4()
    events = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(first), "target_session_id": str(B)},
        ),
        event(
            2,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(second), "target_session_id": str(c)},
            segment=B,
            sequence=0,
        ),
        event(
            3,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(second), "parent_session_id": str(B)},
            segment=c,
            sequence=0,
        ),
        event(
            4,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(first), "parent_session_id": str(A)},
            segment=B,
            sequence=1,
        ),
    )
    proof = ProjectionHandoffProof(first, source_header(events[1]), source_header(events[4]))
    port, scope = _materialize_with_proofs(events, (proof,), 256)
    assert restored(port, scope, events) == list(
        AgUiTaskProjector().project_task_events(events, IDENTITY)
    )
    assert not any(
        cell.key == ProjectionCellKey(B, "handoff", str(second)) for _, cell in port.cells
    )
    assert not any(
        cell.key == ProjectionCellKey(c, "run_member", "member") for _, cell in port.cells
    )


def test_late_handoff_cannot_rewrite_previously_unprojected_source_coverage() -> None:
    handoff = uuid4()
    events = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(1, EventType.MODEL_REQUEST_STARTED, {}, segment=B, sequence=0),
        event(
            2,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(B)},
            sequence=1,
        ),
        event(
            3,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(A)},
            segment=B,
            sequence=1,
        ),
    )
    port, scope = materialize(events[:2])
    port.source.update((entry.task_sequence, entry) for entry in events[2:])
    _, run, decisions = plans(events)
    old = port.read_checkpoint_head(scope)
    with pytest.raises(CheckpointConflict, match="retroactively"):
        AgUiCheckpointMaterializer(port).prepare_page(
            TaskEventPage(events[2:], 1, 3, 100),
            ProjectionPagePlan(run, decisions[2:]),
            scope,
            IDENTITY,
        )
    assert port.read_checkpoint_head(scope) == old


def test_future_and_foreign_point_rows_are_rejected_before_projector() -> None:
    events = (
        event(
            0,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "call", "assistant_message": "hi"},
        ),
    )
    port, scope = materialize(events)
    spy = CountingProjector()
    for bad in (
        ProjectionCell(ProjectionCellKey(A, "text_message", "call"), 0, "message:call"),
        ProjectionCell(ProjectionCellKey(B, "text_message", "call"), 0, "message:call"),
    ):
        port.read_cells_at = lambda *args, row=bad: (row,)
        with pytest.raises(CheckpointConflict, match="foreign/future"):
            AgUiCheckpointMaterializer(port, spy).restore_event_frames(
                scope,
                events[0],
                IDENTITY,
                run=port.runs[scope],
            )
    assert spy.calls == 0


def test_missing_checkpoint_is_explicit_not_history_hydration() -> None:
    events = (event(0, EventType.SESSION_CREATED, {}),)
    port = MemoryCheckpoints(events)
    scope, run, _ = plans(events)
    with pytest.raises(CheckpointNotReady):
        AgUiCheckpointMaterializer(port).restore_event_frames(scope, events[0], IDENTITY, run=run)


def test_unresolved_future_pair_holds_frontier_before_projecting_prefix() -> None:
    handoff = uuid4()
    events = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(B)},
        ),
        event(2, EventType.MODEL_REQUEST_STARTED, {}, segment=B, sequence=0),
        event(
            3,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(A)},
            segment=B,
            sequence=1,
        ),
    )
    scope, run, decisions = plans(events)
    port, spy = MemoryCheckpoints(events), CountingProjector()
    with pytest.raises(CheckpointNotReady, match="resolved paired"):
        AgUiCheckpointMaterializer(port, spy).prepare_page(
            TaskEventPage(events[:3], -1, 3, 100),
            ProjectionPagePlan(run, decisions[:3]),
            scope,
            IDENTITY,
        )
    assert spy.calls == 0 and port.read_checkpoint_head(scope).through_sequence == -1


def test_lookahead_chain_rejects_a_source_admitted_after_its_commit() -> None:
    c = SessionId(uuid4())
    first, second = uuid4(), uuid4()
    events = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(first), "target_session_id": str(B)},
        ),
        event(
            2,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(second), "target_session_id": str(c)},
            segment=B,
            sequence=0,
        ),
        event(
            3,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(second), "parent_session_id": str(B)},
            segment=c,
            sequence=0,
        ),
        event(
            4,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(first), "parent_session_id": str(A)},
            segment=B,
            sequence=1,
        ),
    )
    scope, run, decisions = plans(events)
    proofs = (
        ProjectionHandoffProof(first, source_header(events[1]), source_header(events[4])),
        ProjectionHandoffProof(second, source_header(events[2]), source_header(events[3])),
    )
    port, spy = MemoryCheckpoints(events), CountingProjector()
    with pytest.raises(CheckpointConflict, match="not yet admitted"):
        AgUiCheckpointMaterializer(port, spy).prepare_page(
            TaskEventPage(events, -1, 4, 100),
            ProjectionPagePlan(run, decisions, proofs),
            scope,
            IDENTITY,
        )
    assert spy.calls == 0 and not port.cells


def test_superseded_pair_cannot_admit_target_from_an_older_commit() -> None:
    c, handoff = SessionId(uuid4()), uuid4()
    events = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(B)},
        ),
        event(
            2,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(c)},
        ),
        event(
            3,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(A)},
            segment=B,
            sequence=0,
        ),
    )
    scope, run, decisions = plans(events)
    proof = ProjectionHandoffProof(handoff, source_header(events[1]), source_header(events[3]))
    port, spy = MemoryCheckpoints(events), CountingProjector()
    with pytest.raises(CheckpointConflict, match="superseded"):
        AgUiCheckpointMaterializer(port, spy).prepare_page(
            TaskEventPage(events, -1, 3, 100),
            ProjectionPagePlan(run, decisions, (proof,)),
            scope,
            IDENTITY,
        )
    assert spy.calls == 0 and not port.cells
