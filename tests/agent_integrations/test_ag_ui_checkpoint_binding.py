"""Indexed Page plans match the full-history oracle without importing its scan."""

from dataclasses import replace
from itertools import groupby
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import Session
from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_replay import TaskHandoffHeader, TaskProjectionBlock
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore

from tests.agent_integrations.test_ag_ui_projection_checkpoint import (
    IDENTITY,
    A,
    B,
    MemoryCheckpoints,
    event,
    plans,
    restored,
    source_header,
)


class IndexedMetadata(MemoryCheckpoints):
    """The test builds metadata once; production binding sees only bounded reads."""

    def __init__(self, events):
        super().__init__(events)
        previous, self.blocks, self.handoffs = {}, {}, []
        for segment, values in groupby(events, key=lambda entry: entry.segment_id):
            rows = tuple(values)
            block = TaskProjectionBlock(
                rows[0].task_id,
                segment,
                rows[0].task_sequence,
                rows[-1].task_sequence,
                rows[0].segment_sequence,
                rows[-1].segment_sequence,
                previous.get(segment),
            )
            for row in rows:
                self.blocks[row.task_sequence] = block
                kind, payload = row.event.event_type, row.event.payload
                if kind in {
                    EventType.SESSION_HANDOFF_COMMITTED,
                    EventType.SESSION_HANDOFF_RECEIVED,
                }:
                    field = (
                        "target_session_id"
                        if kind is EventType.SESSION_HANDOFF_COMMITTED
                        else "parent_session_id"
                    )
                    self.handoffs.append(
                        TaskHandoffHeader(
                            source_header(row),
                            UUID(payload["handoff_id"]),
                            SessionId(UUID(payload[field])),
                        )
                    )
            previous[segment] = rows[0].task_sequence
        self.block_reads = self.receive_reads = self.commit_reads = 0

    def read_projection_block(self, task, sequence, *, through_sequence):
        self.block_reads += 1
        block = self.blocks[sequence]
        end = min(block.last_task_sequence, through_sequence)
        return replace(
            block,
            last_task_sequence=end,
            last_segment_sequence=(block.first_segment_sequence + end - block.first_task_sequence),
        )

    def read_handoff_receives(
        self, task, segment, after_sequence=-1, *, through_sequence, limit=256
    ):
        self.receive_reads += 1
        return tuple(
            row
            for row in self.handoffs
            if (
                row.source.segment_id == segment
                and row.source.event_type is EventType.SESSION_HANDOFF_RECEIVED
                and after_sequence < row.source.task_sequence <= through_sequence
            )
        )[:limit]

    def read_latest_handoff_commit(
        self, task, segment, handoff, before_sequence, *, through_sequence
    ):
        self.commit_reads += 1
        return next(
            (
                row
                for row in reversed(self.handoffs)
                if (
                    row.source.segment_id == segment
                    and row.source.event_type is EventType.SESSION_HANDOFF_COMMITTED
                    and row.handoff_id == handoff
                    and row.source.task_sequence < before_sequence
                )
            ),
            None,
        )


def _check(events, chunk):
    port = IndexedMetadata(events)
    scope, run, oracle = plans(events)
    port.runs[scope] = run
    materializer = AgUiCheckpointMaterializer(port)
    for start in range(0, len(events), chunk):
        page = TaskEventPage(events[start : start + chunk], start - 1, run.highwater, 100)
        plan = build_projection_page_plan(port, page, run, scope, IDENTITY)
        assert [(row.projected, row.eligible) for row in plan.events] == [
            (row.projected, row.eligible) for row in oracle[start : start + chunk]
        ]
        transition = materializer.prepare_page(page, plan, scope, IDENTITY)
        assert transition is not None
        port.commit_projection_page(transition)
    assert restored(port, scope, events) == list(
        AgUiTaskProjector().project_task_events(events, IDENTITY)
    )
    return port


def _command(position: int = 0, run: str = "run", **kwargs: Any) -> TaskEvent:
    return event(
        position,
        EventType.SESSION_COMMAND_ACCEPTED,
        {"kind": "run", "payload": {"run_id": run}},
        **kwargs,
    )


@pytest.mark.parametrize("chunk", [1, 7, 64, 256])
def test_future_receive_warms_all_selected_prefix_and_revisited_segment(chunk):
    handoff = uuid4()
    rows = (
        event(
            0, EventType.MODEL_RESPONSE_DELTA, {"model_call_id": "root", "content_delta": "before"}
        ),
        _command(1),
        event(
            2,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(B)},
        ),
        *(
            event(
                i + 3,
                EventType.MODEL_RESPONSE_DELTA,
                {"model_call_id": "child", "content_delta": "x"},
                segment=B,
                sequence=i,
            )
            for i in range(300)
        ),
        event(
            303,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(A)},
            segment=B,
            sequence=300,
        ),
        event(
            304,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "child", "assistant_message": "x" * 300},
            segment=B,
            sequence=301,
        ),
        event(
            305,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "root", "assistant_message": "before after"},
            sequence=3,
        ),
    )
    _check(rows, chunk)


@pytest.mark.parametrize("chunk", [1, 2, 256])
@pytest.mark.parametrize("case", ["orphan", "conflict", "before-parent", "paired"])
def test_only_latest_causally_admitted_parent_authorizes_child(case, chunk):
    c, first, second = SessionId(uuid4()), uuid4(), uuid4()
    rows = [
        _command(),
        event(
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(first), "target_session_id": str(B)},
        ),
    ]
    if case == "paired":
        rows.extend(
            [
                event(
                    2,
                    EventType.SESSION_HANDOFF_RECEIVED,
                    {"handoff_id": str(first), "parent_session_id": str(A)},
                    segment=B,
                    sequence=0,
                ),
                event(
                    3,
                    EventType.SESSION_HANDOFF_COMMITTED,
                    {"handoff_id": str(second), "target_session_id": str(c)},
                    segment=B,
                    sequence=1,
                ),
            ]
        )
    else:
        rows.extend(
            [
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
                    {"handoff_id": str(first), "parent_session_id": str(A)},
                    segment=B,
                    sequence=1,
                ),
            ]
        )
    if case == "conflict":
        rows.append(
            event(
                4,
                EventType.SESSION_HANDOFF_COMMITTED,
                {"handoff_id": str(second), "target_session_id": str(A)},
                segment=B,
                sequence=2,
            )
        )
    position = len(rows)
    rows.extend(
        [
            event(
                position,
                EventType.SESSION_HANDOFF_RECEIVED,
                {
                    "handoff_id": str(uuid4() if case == "orphan" else second),
                    "parent_session_id": str(B),
                },
                segment=c,
                sequence=0,
            ),
            event(
                position + 1,
                EventType.MODEL_RESPONSE_RECEIVED,
                {"assistant_message": "child"},
                segment=c,
                sequence=1,
            ),
        ]
    )
    # Negative membership waits for the canonical next Run to seal this window;
    # retain the same causal cases and the unchanged full-history replay oracle.
    if case != "paired":
        rows.append(_command(len(rows), "next", sequence=2))
    _check(tuple(rows), chunk)


@pytest.mark.parametrize("chunk", [1, 256])
def test_next_run_stops_selection_and_unselected_prefix_never_warms(chunk):
    rows = (
        event(
            0, EventType.MODEL_RESPONSE_DELTA, {"content_delta": "foreign"}, segment=B, sequence=0
        ),
        _command(1, sequence=0),
        event(2, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "first"}, sequence=1),
        _command(3, "next", sequence=2),
        event(4, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "next"}, sequence=3),
    )
    port = _check(rows, chunk)
    assert not any(scalar.segment_id == B for _, scalar in port.scalars)


def test_foreign_scope_fails_before_metadata_queries():
    rows = (_command(),)
    port = IndexedMetadata(rows)
    scope, run, _ = plans(rows)
    with pytest.raises(AgUiProjectionError, match="another Task/run"):
        build_projection_page_plan(
            port,
            TaskEventPage(rows, -1, 0, 100),
            run,
            scope,
            IDENTITY.model_copy(update={"run_id": "other"}),
        )
    assert port.block_reads == port.receive_reads == port.commit_reads == 0


def test_broken_block_identity_fails_without_projection():
    rows = (_command(),)
    port = IndexedMetadata(rows)
    port.blocks[0] = replace(port.blocks[0], task_id=TaskId(uuid4()))
    scope, run, _ = plans(rows)
    with pytest.raises(CheckpointConflict, match="block"):
        build_projection_page_plan(port, TaskEventPage(rows, -1, 0, 100), run, scope, IDENTITY)
    assert not port.headers


def test_orphan_budget_is_explicit_not_false_nonmembership():
    rows = (
        _command(),
        *(
            event(
                i + 1,
                EventType.SESSION_HANDOFF_RECEIVED,
                {"handoff_id": str(uuid4()), "parent_session_id": str(A)},
                segment=B,
                sequence=i,
            )
            for i in range(257)
        ),
    )
    port = IndexedMetadata(rows)
    scope, run, _ = plans(rows)
    with pytest.raises(CheckpointNotReady, match="row budget"):
        build_projection_page_plan(
            port, TaskEventPage(rows[:2], -1, run.highwater, 100), run, scope, IDENTITY
        )
    assert not port.headers


def test_real_sqlite_facade_builder_cold_restore_no_read_events(tmp_path):
    path = tmp_path / "binding.sqlite"
    root, child = Session.create(title="Root"), Session.create(title="Child")
    events, projections, tasks = (
        SQLiteEventStore(path),
        SQLiteProjectionStore(path),
        SQLiteAgentTaskStore(path),
    )
    for session in (root, child):
        source = SessionEvent.create(
            session_id=session.session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": session.title},
        )
        events.append(source)
        projections.save_session(session)
    task = tasks.ensure_for_session(root.session_id)
    tasks.attach_segment(
        task.task_id,
        child.session_id,
        predecessor_id=root.session_id,
        reason=RolloverReason.RECOVERY,
    )
    handoff = uuid4()
    for segment, sequence, kind, payload in (
        (
            root.session_id,
            1,
            EventType.SESSION_COMMAND_ACCEPTED,
            {"kind": "run", "payload": {"run_id": "run"}},
        ),
        (
            root.session_id,
            2,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(child.session_id)},
        ),
        (
            child.session_id,
            1,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(root.session_id)},
        ),
        (
            child.session_id,
            2,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"assistant_message": "first result"},
        ),
        (
            root.session_id,
            3,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"assistant_message": "final result"},
        ),
    ):
        if kind is EventType.SESSION_COMMAND_ACCEPTED:
            payload = {
                **payload,
                "command_id": str(uuid4()),
                "session_id": str(segment),
                "expected_revision": sequence - 1,
                "idempotency_key": "binding-run",
                "fingerprint": "a" * 64,
            }
        elif kind is EventType.SESSION_HANDOFF_COMMITTED:
            payload = {
                **payload,
                "reason": "internal_recovery",
                "target_stage_index": 1,
                "source_event_range": {"start_sequence": 0, "end_sequence": 1},
                "source_event_hash": "a" * 64,
                "artifact_id": "binding-capsule",
                "checksum": "a" * 64,
                "idempotency_key_hash": "a" * 64,
            }
        elif kind is EventType.SESSION_HANDOFF_RECEIVED:
            payload = {
                **payload,
                "root_session_id": str(root.session_id),
                "stage_index": 1,
                "artifact_id": "binding-capsule",
                "checksum": "a" * 64,
            }
        events.append(
            SessionEvent.create(
                session_id=segment,
                sequence=sequence,
                event_type=kind,
                actor=EventActor.HARNESS,
                payload=payload,
            )
        )
    while not tasks.backfill_replay_headers(task.task_id):
        pass
    while not tasks.backfill_projection_sources(task.task_id):
        pass
    source = tasks.read_events(task.task_id, -1)  # Oracle only, before forbidding it.
    identity = AgUiRunIdentity(
        session_id=root.session_id, thread_id=str(task.task_id), run_id="run"
    )
    run = tasks.read_run_header(task.task_id, "run")
    from agent_core.ports.task_projection_checkpoints import ProjectionScope

    scope = ProjectionScope("local", task.task_id, run.anchor.event_id, "ag-ui-v1")

    def forbidden(*args):
        raise AssertionError("full history hydrated")

    tasks.read_events = forbidden
    materializer = AgUiCheckpointMaterializer(tasks)
    after = -1
    while after < run.highwater:
        page = tasks.read_event_page(task.task_id, after, limit=1)
        plan = build_projection_page_plan(tasks, page, run, scope, identity)
        tasks.commit_projection_page(materializer.prepare_page(page, plan, scope, identity))
        after = page.next_sequence
    cold = SQLiteAgentTaskStore(path)
    cold.read_events = forbidden
    actual = []
    for position in range(run.highwater + 1):
        entry = cold.read_event_page(task.task_id, position - 1, limit=1).events[0]
        if cold.read_event_projection_header(scope, position).eligible:
            actual.extend(
                AgUiCheckpointMaterializer(cold).iter_event_frames(scope, entry, identity, run=run)
            )
    assert actual == list(AgUiTaskProjector().project_task_events(source, identity))
