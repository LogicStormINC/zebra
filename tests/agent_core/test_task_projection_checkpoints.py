"""Runnable trust-boundary checks for bounded derived projection records."""

from dataclasses import replace
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import EventId, SessionId, TaskId
from agent_core.ports.task_projection_checkpoints import (
    ProjectionCell,
    ProjectionCellKey,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
)


def _scope() -> ProjectionScope:
    return ProjectionScope("namespace", TaskId(uuid4()), EventId(uuid4()), "ag-ui-v1")


def _header(position: int = 0) -> ProjectionFrameHeader:
    return ProjectionFrameHeader(
        position,
        EventId(uuid4()),
        SessionId(uuid4()),
        position,
        -1,
        3,
        True,
        True,
    )


def _transition() -> ProjectionTransition:
    header = _header()
    scalar = SegmentCheckpoint(header.segment_id, 0, 0, True, False)
    key = ProjectionCellKey(header.segment_id, "tool_call", "call")
    return ProjectionTransition(_scope(), -1, (header,), (scalar,), (ProjectionCell(key, 0, "1"),))


def test_transition_has_small_records_no_body_and_exact_frontier() -> None:
    transition = _transition()
    assert transition.through_sequence == 0
    assert transition.byte_count < 2_048
    assert not hasattr(transition.headers[0], "payload")
    assert not hasattr(transition.scalars[0], "cells")
    assert replace(transition.cells[0], value=None).value is None


@pytest.mark.parametrize("field,value", [("namespace", ""), ("projector_version", "x" * 65)])
def test_scope_rejects_unbounded_or_empty_identity(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        replace(_scope(), **{field: value})


@pytest.mark.parametrize("value", [True, -2, 1.5])
def test_coordinates_are_strict_integers(value: object) -> None:
    with pytest.raises(ValueError):
        replace(_header(), state_before_sequence=value)


@pytest.mark.parametrize(
    "changes",
    [
        {"state_before_sequence": 0},
        {"frame_count": 4_097},
        {"frame_count": True},
        {"projected": False},
        {"eligible": 1},
    ],
)
def test_frame_header_rejects_future_state_or_malformed_frames(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(_header(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"headers": ()},
        {"expected_through": 0},
        {"scalars": ()},
        {"terminal_sequence": 1},
    ],
)
def test_transition_rejects_incomplete_or_misaligned_publication(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_transition(), **changes)


def test_duplicate_scalar_cell_and_event_versions_are_rejected() -> None:
    transition = _transition()
    for changes in (
        {"scalars": transition.scalars * 2},
        {"cells": transition.cells * 2},
        {"headers": transition.headers * 2},
    ):
        with pytest.raises(ValueError):
            replace(transition, **changes)


def test_frontier_cannot_publish_a_future_or_ineligible_locator() -> None:
    header = _header(1)
    with pytest.raises(ValueError):
        ProjectionCheckpointHead(_scope(), 0, EventId(uuid4()), header)
    with pytest.raises(ValueError):
        ProjectionCheckpointHead(_scope(), 1, None)
    with pytest.raises(ValueError):
        ProjectionCheckpointHead(_scope(), 1, EventId(uuid4()), replace(header, eligible=False))


def test_cell_bounds_and_membership_values_are_checked() -> None:
    key = _transition().cells[0].key
    with pytest.raises(ValueError):
        ProjectionCell(key, 0, "not-membership")
    with pytest.raises(ValueError):
        replace(key, key="字" * 342)
    with pytest.raises(ValueError):
        ProjectionCell(replace(key, kind="text_message"), 0, "x" * 2_049)


def test_transition_byte_limit_cannot_be_bypassed_by_many_large_cells() -> None:
    transition = _transition()
    segment = transition.headers[0].segment_id
    cells = tuple(
        ProjectionCell(ProjectionCellKey(segment, "text_message", str(i)), 0, "v" * 2_048)
        for i in range(512)
    )
    with pytest.raises(ValueError, match="byte bound"):
        replace(transition, cells=cells)


def test_transition_event_and_key_count_limits_are_enforced() -> None:
    transition = _transition()
    headers = tuple(
        replace(_header(i), projected=False, eligible=False, frame_count=0) for i in range(257)
    )
    with pytest.raises(ValueError, match="Event bound"):
        replace(transition, headers=headers, scalars=())
    key = transition.cells[0].key
    cells = tuple(ProjectionCell(replace(key, key=str(i)), 0, "1") for i in range(1_025))
    with pytest.raises(ValueError, match="cell bound"):
        replace(transition, cells=cells)


@pytest.mark.parametrize("kind", ["text_message", "text_ended", "tool_call", "interrupt"])
@pytest.mark.parametrize("tombstone", [False, True])
def test_projector_cells_cannot_mutate_an_unprojected_event(kind: str, tombstone: bool) -> None:
    transition = _transition()
    header = replace(transition.headers[0], projected=False, eligible=False, frame_count=0)
    key = replace(transition.cells[0].key, kind=kind)
    value = None if tombstone else "message" if kind == "text_message" else "1"
    with pytest.raises(ValueError, match="unprojected"):
        replace(transition, headers=(header,), scalars=(), cells=(ProjectionCell(key, 0, value),))


@pytest.mark.parametrize("kind", ["run_member", "handoff"])
@pytest.mark.parametrize("tombstone", [False, True])
def test_binding_cells_remain_legal_on_unprojected_events(kind: str, tombstone: bool) -> None:
    transition = _transition()
    header = replace(transition.headers[0], projected=False, eligible=False, frame_count=0)
    key = replace(transition.cells[0].key, kind=kind)
    cell = ProjectionCell(key, 0, None if tombstone else "1")
    assert replace(transition, headers=(header,), scalars=(), cells=(cell,)).cells == (cell,)


@pytest.mark.parametrize("kind", ["text_message", "text_ended", "tool_call", "interrupt"])
def test_projected_warm_prefix_can_mutate_state_without_public_eligibility(kind: str) -> None:
    transition = _transition()
    header = replace(transition.headers[0], eligible=False)
    key = replace(transition.cells[0].key, kind=kind)
    cell = ProjectionCell(key, 0, "message" if kind == "text_message" else "1")
    assert replace(transition, headers=(header,), cells=(cell,)).cells == (cell,)
