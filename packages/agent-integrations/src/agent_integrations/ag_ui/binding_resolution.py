"""Explicit background attribution using the existing bounded checkpoint CAS.

The separate scope is a scalar cursor/ledger, never output or execution authority.
Every receive is examined once in Task order, so orphans and causal depth survive
restarts without a recursion stack or a query-time prefix scan.
"""

import json
from typing import Literal

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_EVENTS,
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionCheckpointHead,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    TaskProjectionCheckpointPort,
)
from agent_core.ports.task_replay import TaskHandoffHeader, TaskRunHeader

from agent_integrations.ag_ui.checkpoint_plan import (
    AG_UI_CHECKPOINT_VERSION,
    AG_UI_COVERAGE_CHECKPOINT_VERSION,
)

BINDING_VERSION = "ag-ui-binding-v1"
BINDING_PROOF_KEY = "binding:admission"


class BindingResolutionPending(CheckpointNotReady):
    """Expected resumable work/wait, never a queue integrity failure attempt."""

    def __init__(
        self,
        message: str,
        *,
        reason: Literal["budget", "resolution", "admission"],
        resolved_through: int,
        required_through: int,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.resolved_through = resolved_through
        self.required_through = required_through


def binding_scope(scope: ProjectionScope) -> ProjectionScope:
    if scope.projector_version not in {AG_UI_CHECKPOINT_VERSION, AG_UI_COVERAGE_CHECKPOINT_VERSION}:
        raise CheckpointConflict("binding requires the supported output scope")
    return ProjectionScope(scope.namespace, scope.task_id, scope.anchor_event_id, BINDING_VERSION)


def binding_through(run: TaskRunHeader) -> int:
    return min(run.highwater, run.stop - 1 if run.stop is not None else run.highwater)


def validate_binding_scope(run: TaskRunHeader, scope: ProjectionScope) -> None:
    if (
        run.legacy
        or run.control_only
        or run.anchor is None
        or run.task_id != scope.task_id
        or run.anchor.event_id != scope.anchor_event_id
    ):
        raise CheckpointConflict("binding scope conflicts with its canonical Run")
    binding_scope(scope)


def member_key(segment: SessionId) -> ProjectionCellKey:
    return ProjectionCellKey(segment, "run_member", "member")


def binding_member_before(
    port: TaskProjectionCheckpointPort,
    run: TaskRunHeader,
    scope: ProjectionScope,
    segment: SessionId,
    before: int,
) -> int | None:
    """A positive certificate is monotonic; absence is not permanent rejection."""
    validate_binding_scope(run, scope)
    if before <= run.start:
        return None
    if run.anchor is not None and segment == run.anchor.segment_id:
        return run.start
    ledger = binding_scope(scope)
    head = port.read_checkpoint_head(ledger)
    if head.scope != ledger:
        raise CheckpointConflict("binding head belongs to another scope")
    boundary = min(before, binding_through(run) + 1, head.through_sequence + 1)
    if boundary <= run.start:
        return None
    key = member_key(segment)
    rows = port.read_cells_at(ledger, boundary, (key,))
    if len(rows) > 1 or any(
        row.key != key or not run.start <= row.task_sequence < boundary or row.value != "1"
        for row in rows
    ):
        raise CheckpointConflict("binding membership conflicts with its frozen source window")
    return rows[0].task_sequence if rows else None


def checked_handoff(
    row: TaskHandoffHeader,
    run: TaskRunHeader,
    segment: SessionId,
    kind: EventType,
    after: int,
    before: int,
) -> None:
    source = row.source
    if (
        source.task_id != run.task_id
        or source.segment_id != segment
        or source.event_type is not kind
        or not after < source.task_sequence < before
        or source.task_sequence > binding_through(run)
    ):
        raise CheckpointConflict("binding handoff conflicts with canonical source")


def advance_binding_resolution(
    tasks: AgentTaskPort,
    run: TaskRunHeader,
    scope: ProjectionScope,
    *,
    limit: int = MAX_CHECKPOINT_EVENTS,
) -> ProjectionCheckpointHead:
    """Advance one explicit metadata-only transaction, never invoked by reads.

    Shared scalar budget counts source headers AND receive/commit lookup slots.
    A lost CAS publishes no cursor or certificate. New H resumes the same ledger;
    membership is stored at its actual causal receive, not an earlier warm prefix.
    """
    validate_binding_scope(run, scope)
    if type(limit) is not int or not 3 <= limit <= MAX_CHECKPOINT_EVENTS:
        raise ValueError("binding scalar budget must be between 3 and 256")
    ledger = binding_scope(scope)
    head = tasks.read_checkpoint_head(ledger)
    if head.scope != ledger:
        raise CheckpointConflict("binding head belongs to another scope")
    through = binding_through(run)
    if head.through_sequence >= through:
        return head
    headers: list[ProjectionFrameHeader] = []
    changes: list[ProjectionCell] = []
    local: dict[SessionId, int] = {}
    remaining = limit

    def member(segment: SessionId, before: int) -> bool:
        if segment in local and local[segment] < before:
            return True
        return binding_member_before(tasks, run, scope, segment, before) is not None

    for position in range(
        head.through_sequence + 1, min(through, head.through_sequence + limit) + 1
    ):
        if not remaining:
            break
        source = tasks.read_event_header(run.task_id, position)
        remaining -= 1
        if source is None:
            raise CheckpointNotReady("binding canonical source header is not ready")
        if source.task_id != run.task_id or source.task_sequence != position:
            raise CheckpointConflict("binding cursor conflicts with canonical source")
        if position == run.start:
            if source != run.anchor:
                raise CheckpointConflict("binding anchor conflicts with canonical source")
            local[source.segment_id] = position
            changes.append(ProjectionCell(member_key(source.segment_id), position, "1"))
        elif position > run.start and source.event_type is EventType.SESSION_HANDOFF_RECEIVED:
            if remaining < 2:
                break  # No half-receive cursor: the next tick retries this one header.
            remaining -= 2
            rows = tasks.read_handoff_receives(
                run.task_id,
                source.segment_id,
                position - 1,
                through_sequence=position,
                limit=1,
            )
            if len(rows) != 1 or rows[0].source != source:
                raise CheckpointConflict("binding receive metadata conflicts with canonical header")
            receive = rows[0]
            checked_handoff(
                receive,
                run,
                source.segment_id,
                EventType.SESSION_HANDOFF_RECEIVED,
                position - 1,
                position + 1,
            )
            commit = tasks.read_latest_handoff_commit(
                run.task_id,
                receive.peer_segment_id,
                receive.handoff_id,
                position,
                through_sequence=position,
            )
            if commit is not None:
                checked_handoff(
                    commit,
                    run,
                    receive.peer_segment_id,
                    EventType.SESSION_HANDOFF_COMMITTED,
                    -1,
                    position,
                )
                if commit.handoff_id != receive.handoff_id:
                    raise CheckpointConflict("binding commit has another handoff identity")
                if (
                    commit.source.task_sequence >= run.start
                    and commit.peer_segment_id == source.segment_id
                    and member(commit.source.segment_id, commit.source.task_sequence)
                    and not member(source.segment_id, position)
                ):
                    local[source.segment_id] = position
                    changes.extend(
                        (
                            ProjectionCell(member_key(source.segment_id), position, "1"),
                            ProjectionCell(
                                ProjectionCellKey(source.segment_id, "handoff", BINDING_PROOF_KEY),
                                position,
                                json.dumps(
                                    [
                                        str(receive.handoff_id),
                                        str(commit.source.segment_id),
                                        commit.source.task_sequence,
                                    ],
                                    separators=(",", ":"),
                                ),
                            ),
                        )
                    )
        headers.append(
            ProjectionFrameHeader(
                position,
                source.event_id,
                source.segment_id,
                source.segment_sequence,
                -1,
                0,
                False,
                False,
            )
        )
    if not headers:
        raise CheckpointNotReady("binding budget cannot advance its next source header")
    return tasks.commit_projection_page(
        ProjectionTransition(
            ledger,
            head.through_sequence,
            tuple(headers),
            (),
            tuple(changes),
        )
    )
