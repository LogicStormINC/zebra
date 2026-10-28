"""Read-only public slice resolution at an exact native command coordinate."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionScope,
)
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.ag_ui.standard_checkpoint import load_standard
from agent_integrations.ag_ui.standard_state import StandardProjectionState


@dataclass(frozen=True, slots=True)
class AgUiPublicSlice:
    scope: ProjectionScope
    internal_run_id: str
    run_id: str
    source: TaskEventHeader
    previous_run_id: str | None
    turn_finished: bool
    status: str | None


@dataclass(frozen=True, slots=True)
class AgUiPublicResolution:
    kind: Literal["new_public_run", "same_public_run", "no_public_successor"]
    protocol_run_id: str
    continuation_id: str
    previous_run_id: str | None
    turn_finished: bool
    status: str | None
    slice: AgUiPublicSlice | None = None


def standard_state_after(
    tasks: AgentTaskPort,
    scope: ProjectionScope,
    run: TaskRunHeader,
    source: TaskEventHeader,
) -> StandardProjectionState:
    """No future state, event-body scan, repair, or new identity ledger."""
    if run.anchor is None or tasks.read_event_header(run.task_id, source.task_sequence) != source:
        raise CheckpointConflict("public binding requires an exact canonical source")
    head = tasks.read_checkpoint_head(scope)
    if head.scope != scope:
        raise CheckpointConflict("public binding checkpoint scope conflicts")
    if head.through_sequence < source.task_sequence:
        raise CheckpointNotReady("public binding has not reached its source")
    return load_standard(
        run.anchor.segment_id,
        lambda keys: tasks.read_cells_at(scope, source.task_sequence + 1, keys),
        required=True,
    )


def resolve_public_continuation(
    tasks: AgentTaskPort,
    *,
    namespace: str,
    task_id: TaskId,
    internal_run_id: str,
    source: TaskEventHeader,
    profile: AgUiProjectionProfile,
) -> AgUiPublicResolution:
    """An internal resume may keep the active public Run or be ignored entirely."""
    if not issubclass(profile.state_type, StandardProjectionState):
        raise CheckpointConflict("public slices require the standard state binding")
    run = tasks.read_run_header(task_id, internal_run_id)
    if run.task_id != task_id or run.run_id != internal_run_id:
        raise CheckpointConflict("public binding belongs to another native Run")
    if run.anchor is None:
        raise CheckpointNotReady("native admission anchor is not ready")
    scope = ProjectionScope(
        namespace,
        task_id,
        run.anchor.event_id,
        profile.checkpoint_version(coverage=run.strict_coverage),
    )
    expected = profile.protocol_run_id(tasks, scope, run, source)
    state = standard_state_after(tasks, scope, run, source)
    if state.protocol_run_id is None or state.continuation_id is None:
        raise CheckpointConflict("standard state omits its public binding")
    if state.protocol_run_id != profile.protocol_id_for_anchor(
        scope, run, UUID(state.continuation_id)
    ):
        raise CheckpointConflict("public state belongs to another profile binding")
    if state.continuation_id != str(source.event_id):
        return AgUiPublicResolution(
            "no_public_successor" if state.turn_finished else "same_public_run",
            state.protocol_run_id,
            state.continuation_id,
            state.previous_protocol_run_id,
            state.turn_finished,
            state.public_execution.get("status"),
        )
    if state.protocol_run_id != expected:
        raise CheckpointConflict("public state conflicts with canonical binding")
    public = AgUiPublicSlice(
        scope,
        internal_run_id,
        expected,
        source,
        state.previous_protocol_run_id,
        state.turn_finished,
        state.public_execution.get("status"),
    )
    return AgUiPublicResolution(
        "new_public_run",
        expected,
        state.continuation_id,
        state.previous_protocol_run_id,
        state.turn_finished,
        state.public_execution.get("status"),
        public,
    )


def resolve_public_slice(
    tasks: AgentTaskPort,
    *,
    namespace: str,
    task_id: TaskId,
    internal_run_id: str,
    source: TaskEventHeader,
    profile: AgUiProjectionProfile,
) -> AgUiPublicSlice | None:
    return resolve_public_continuation(
        tasks,
        namespace=namespace,
        task_id=task_id,
        internal_run_id=internal_run_id,
        source=source,
        profile=profile,
    ).slice
