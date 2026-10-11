"""Resumable scalar attribution and immutable publication against the full oracle."""

from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCell,
    ProjectionCheckpointHead,
    ProjectionScope,
)
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import ProjectionEventPlan, ProjectionPagePlan
from agent_integrations.ag_ui.task_stream import AgUiTaskProjector

from tests.agent_integrations.test_ag_ui_checkpoint_binding import IndexedMetadata, _command
from tests.agent_integrations.test_ag_ui_projection_checkpoint import (
    IDENTITY,
    A,
    B,
    event,
    plans,
    restored,
    source_header,
)


class ScalarMetadata(IndexedMetadata):
    def __init__(self, events: tuple[TaskEvent, ...]) -> None:
        super().__init__(events)  # type: ignore[no-untyped-call] # Existing test metadata fixture.

    def read_event_header(self, task: TaskId, position: int) -> TaskEventHeader:
        return source_header(self.source[position])


def _advance(
    port: ScalarMetadata,
    run: TaskRunHeader,
    scope: ProjectionScope,
    limit: int = 64,
) -> ProjectionCheckpointHead:
    from agent_integrations.ag_ui.binding_resolution import advance_binding_resolution

    return advance_binding_resolution(cast(AgentTaskPort, port), run, scope, limit=limit)


def _drain(
    port: ScalarMetadata,
    run: TaskRunHeader,
    scope: ProjectionScope,
    limit: int = 64,
) -> None:
    through = min(run.highwater, run.stop - 1 if run.stop is not None else run.highwater)
    while _advance(port, run, scope, limit).through_sequence < through:
        pass


def _publish(
    port: ScalarMetadata,
    rows: tuple[TaskEvent, ...],
    run: TaskRunHeader,
    scope: ProjectionScope,
    chunk: int = 16,
) -> None:
    port.runs[scope] = run
    materializer = AgUiCheckpointMaterializer(port)
    after = port.read_checkpoint_head(scope).through_sequence
    while after < len(rows) - 1:
        page = TaskEventPage(rows[after + 1 : after + 1 + chunk], after, run.highwater, 100)
        plan = build_projection_page_plan(cast(AgentTaskPort, port), page, run, scope, IDENTITY)
        transition = materializer.prepare_page(page, plan, scope, IDENTITY)
        assert transition is not None
        port.commit_projection_page(transition)
        after = page.next_sequence


def test_open_unknown_block_has_no_permanent_negative_header() -> None:
    rows = (
        _command(),
        event(
            1,
            EventType.MODEL_RESPONSE_DELTA,
            {"model_call_id": "child", "content_delta": "prefix"},
            segment=B,
            sequence=0,
        ),
    )
    port = ScalarMetadata(rows)
    scope, run, _ = plans(rows)
    with pytest.raises(CheckpointNotReady, match="admission|closure"):
        build_projection_page_plan(
            cast(AgentTaskPort, port),
            TaskEventPage(rows, -1, 1, 100),
            run,
            scope,
            IDENTITY,
        )
    assert not port.headers


@pytest.mark.parametrize("chunk", [1, 64, 256])
def test_incremental_highwater_admits_whole_prefix_without_changing_old_headers(chunk: int) -> None:
    handoff = uuid4()
    rows = (
        event(0, EventType.MODEL_RESPONSE_DELTA, {"model_call_id": "root", "content_delta": "r"}),
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
            {"model_call_id": "root", "assistant_message": "root"},
            sequence=3,
        ),
    )
    port = ScalarMetadata(rows)
    scope, run, _ = plans(rows)
    early = replace(run, highwater=100)
    _drain(port, early, scope)
    _publish(port, rows[:3], early, scope)
    frozen = dict(port.headers)
    with pytest.raises(CheckpointNotReady):
        _publish(port, rows[:101], early, scope)
    assert port.headers == frozen
    _drain(port, run, scope)
    _publish(port, rows, run, scope, chunk)
    assert all(port.headers[key] == value for key, value in frozen.items())
    assert restored(port, scope, rows) == list(
        AgUiTaskProjector().project_task_events(rows, IDENTITY)
    )


def test_over_256_orphans_resume_from_durable_cursor_then_admit() -> None:
    handoff = uuid4()
    rows = (
        _command(),
        event(
            1,
            EventType.MODEL_RESPONSE_DELTA,
            {"model_call_id": "child", "content_delta": "prefix"},
            segment=B,
            sequence=0,
        ),
        *(
            event(
                i + 2,
                EventType.SESSION_HANDOFF_RECEIVED,
                {"handoff_id": str(uuid4()), "parent_session_id": str(A)},
                segment=B,
                sequence=i + 1,
            )
            for i in range(600)
        ),
        event(
            602,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(B)},
            sequence=1,
        ),
        event(
            603,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(A)},
            segment=B,
            sequence=601,
        ),
        event(
            604,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": "child", "assistant_message": "prefix final"},
            segment=B,
            sequence=602,
        ),
    )
    port = ScalarMetadata(rows)
    scope, run, _ = plans(rows)
    head = _advance(port, run, scope, 256)
    assert 0 < head.through_sequence < 256
    cold = ScalarMetadata(rows)
    for name in ("heads", "headers", "cells", "scalars"):
        setattr(cold, name, getattr(port, name))
    _drain(cold, run, scope, 128)
    assert cold.receive_reads == 601 - (head.through_sequence - 1)
    _publish(cold, rows, run, scope)
    assert restored(cold, scope, rows) == list(
        AgUiTaskProjector().project_task_events(rows, IDENTITY)
    )


def test_deep_chain_uses_direct_certificates_not_recursive_page_proofs() -> None:
    rows, parent = [_command()], A
    for _ in range(300):
        child, handoff = SessionId(uuid4()), uuid4()
        rows.append(
            event(
                len(rows),
                EventType.SESSION_HANDOFF_COMMITTED,
                {"handoff_id": str(handoff), "target_session_id": str(child)},
                segment=parent,
                sequence=1,
            )
        )
        rows.append(
            event(
                len(rows),
                EventType.SESSION_HANDOFF_RECEIVED,
                {"handoff_id": str(handoff), "parent_session_id": str(parent)},
                segment=child,
                sequence=0,
            )
        )
        parent = child
    rows.append(
        event(
            len(rows),
            EventType.MODEL_RESPONSE_RECEIVED,
            {"assistant_message": "leaf"},
            segment=parent,
            sequence=1,
        )
    )
    source = tuple(rows)
    port = ScalarMetadata(source)
    scope, run, _ = plans(source)
    _drain(port, run, scope)
    _publish(port, source, run, scope, 256)
    assert restored(port, scope, source) == list(
        AgUiTaskProjector().project_task_events(source, IDENTITY)
    )


def test_closed_unselected_segment_never_warms() -> None:
    rows = (
        _command(),
        event(
            1, EventType.MODEL_RESPONSE_DELTA, {"content_delta": "foreign"}, segment=B, sequence=0
        ),
        _command(2, "next", sequence=1),
    )
    port = ScalarMetadata(rows)
    scope, run, _ = plans(rows)
    _drain(port, run, scope)
    _publish(port, rows, run, scope)
    assert not any(s.segment_id == B for _, s in port.scalars)
    assert restored(port, scope, rows) == list(
        AgUiTaskProjector().project_task_events(rows, IDENTITY)
    )


@pytest.mark.parametrize("phase", ["budget", "resolution", "admission"])
def test_pending_categories_resume_or_wait_without_publishing_or_repair(phase: str) -> None:
    from agent_integrations.ag_ui.binding_resolution import BindingResolutionPending

    rows = (
        _command(),
        *(
            event(
                n + 1,
                EventType.SESSION_HANDOFF_RECEIVED,
                {"handoff_id": str(uuid4()), "parent_session_id": str(A)},
                segment=B,
                sequence=n,
            )
            for n in range(300)
        ),
    )
    port = ScalarMetadata(rows)
    scope, run, _ = plans(rows)
    if phase == "resolution":
        first = _advance(port, run, scope)
        assert 0 < first.through_sequence < run.highwater
    elif phase == "admission":
        _drain(port, run, scope)
    page = TaskEventPage(rows[:64], -1, run.highwater, 100)
    with pytest.raises(BindingResolutionPending) as caught:
        build_projection_page_plan(cast(AgentTaskPort, port), page, run, scope, IDENTITY)
    pending = caught.value
    assert pending.reason == phase and pending.required_through == run.highwater
    assert port.read_checkpoint_head(scope).through_sequence == -1
    if phase != "admission":
        updated = _advance(port, run, scope)
        assert updated.through_sequence > pending.resolved_through
    else:
        # Waiting at H cannot progress by re-scanning the source or publishing False.
        reads = port.receive_reads, port.commit_reads
        assert _advance(port, run, scope).through_sequence == pending.resolved_through
        assert (port.receive_reads, port.commit_reads) == reads


def test_page_256_disjoint_parents_prefetches_exactly_1024_keyed_cells() -> None:
    rows, leaves = [_command()], []
    for n in range(256):
        parent, leaf = SessionId(uuid4()), SessionId(uuid4())
        leaves.append(leaf)
        for origin, target, sequence in ((A, parent, n + 1), (parent, leaf, 1)):
            handoff = uuid4()
            rows.append(
                event(
                    len(rows),
                    EventType.SESSION_HANDOFF_COMMITTED,
                    {"handoff_id": str(handoff), "target_session_id": str(target)},
                    segment=origin,
                    sequence=sequence,
                )
            )
            rows.append(
                event(
                    len(rows),
                    EventType.SESSION_HANDOFF_RECEIVED,
                    {"handoff_id": str(handoff), "parent_session_id": str(origin)},
                    segment=target,
                    sequence=0,
                )
            )
    start = len(rows)
    for leaf in leaves:
        rows.append(
            event(
                len(rows),
                EventType.SESSION_TITLE_UPDATED,
                {"title": "late"},
                segment=leaf,
                sequence=1,
            )
        )
    source = tuple(rows)
    port = ScalarMetadata(source)
    scope, run, _ = plans(source)
    _drain(port, run, scope)
    port.requests.clear()
    before = port.block_reads, port.receive_reads, port.commit_reads
    page = TaskEventPage(source[start:], start - 1, run.highwater, 100)
    plan = build_projection_page_plan(cast(AgentTaskPort, port), page, run, scope, IDENTITY)
    assert all(row.projected and row.eligible for row in plan.events)
    assert len(plan.handoffs) == 256
    assert [len(keys) for _, keys in port.requests] == [512, 512]
    assert tuple(
        current - previous
        for current, previous in zip(
            (port.block_reads, port.receive_reads, port.commit_reads), before, strict=True
        )
    ) == (256, 256, 256)


def test_malformed_durable_certificate_is_conflict_not_pending() -> None:
    from agent_integrations.ag_ui.binding_resolution import BINDING_PROOF_KEY, binding_scope

    handoff = uuid4()
    rows = (
        _command(),
        event(
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(B)},
            sequence=1,
        ),
        event(
            2,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(A)},
            segment=B,
            sequence=0,
        ),
    )
    port = ScalarMetadata(rows)
    scope, run, _ = plans(rows)
    _drain(port, run, scope)
    for n, (owner, cell) in enumerate(port.cells):
        if owner == binding_scope(scope) and cell.key.key == BINDING_PROOF_KEY:
            port.cells[n] = owner, ProjectionCell(cell.key, cell.task_sequence, "not-json")
    with pytest.raises(CheckpointConflict, match="malformed"):
        build_projection_page_plan(
            cast(AgentTaskPort, port),
            TaskEventPage(rows, -1, run.highwater, 100),
            run,
            scope,
            IDENTITY,
        )


def test_old_negative_coverage_rejects_late_pair_before_receive_page() -> None:
    handoff = uuid4()
    rows = (
        _command(),
        event(
            1,
            EventType.SESSION_HANDOFF_COMMITTED,
            {"handoff_id": str(handoff), "target_session_id": str(B)},
            sequence=1,
        ),
        event(2, EventType.MODEL_REQUEST_STARTED, {}, segment=B, sequence=0),
        event(
            3,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"assistant_message": "late"},
            segment=B,
            sequence=1,
        ),
        event(
            4,
            EventType.SESSION_HANDOFF_RECEIVED,
            {"handoff_id": str(handoff), "parent_session_id": str(A)},
            segment=B,
            sequence=2,
        ),
    )
    port = ScalarMetadata(rows)
    scope, run, decisions = plans(rows)
    early = replace(run, highwater=2)
    # Simulate a pre-ledger writer that already published permanent False coverage.
    old_plan = ProjectionPagePlan(
        early, (*decisions[:2], ProjectionEventPlan(source_header(rows[2]), False, False))
    )
    materializer = AgUiCheckpointMaterializer(port)
    transition = materializer.prepare_page(
        TaskEventPage(rows[:3], -1, 2, 100), old_plan, scope, IDENTITY
    )
    assert transition is not None
    port.commit_projection_page(transition)
    old_headers = dict(port.headers)
    _drain(port, run, scope)
    page = TaskEventPage(rows[3:4], 2, run.highwater, 100)
    plan = build_projection_page_plan(cast(AgentTaskPort, port), page, run, scope, IDENTITY)
    assert plan.events[0].projected
    with pytest.raises(CheckpointConflict, match="retroactively"):
        materializer.prepare_page(page, plan, scope, IDENTITY)
    assert port.read_checkpoint_head(scope).through_sequence == 2
    assert all(port.headers[key] == value for key, value in old_headers.items())
