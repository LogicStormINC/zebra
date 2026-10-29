"""Canonical per-Event public identity, reconstructed without mutable projector context."""

from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEvent
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader

from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.ag_ui.standard_state import StandardProjectionState


def bind_standard(
    profile: AgUiProjectionProfile,
    scope: ProjectionScope,
    run: TaskRunHeader,
    source: TaskEventHeader,
    state: StandardProjectionState,
) -> None:
    anchor = run.anchor
    if anchor is None:
        raise AgUiProjectionError("standard producer requires an immutable Run anchor")
    if (
        state.protocol_run_id is not None
        and state.protocol_run_id
        != profile.protocol_id_for_anchor(scope, run, UUID(str(state.continuation_id)))
    ):
        raise AgUiProjectionError("standard checkpoint belongs to another public Run binding")
    if state.protocol_run_id is None:
        chosen = anchor
    elif (
        source.internal_continuation
        and state.turn_finished
        and state.public_execution.get("status") in {"paused", "waiting_input"}
    ):
        chosen = source
    else:
        return
    state.begin(profile.protocol_anchor_id(scope, run, chosen), str(chosen.event_id))


def standard_header(entry: TaskEvent) -> TaskEventHeader:
    from agent_integrations.ag_ui.task_run_binding import _is_internal_continuation, command_run_id

    command = entry.event.event_type is EventType.SESSION_COMMAND_ACCEPTED
    return TaskEventHeader(
        task_id=entry.task_id,
        task_sequence=entry.task_sequence,
        event_id=entry.event.event_id,
        segment_id=entry.segment_id,
        segment_sequence=entry.segment_sequence,
        event_type=entry.event.event_type,
        command_kind=entry.event.payload.get("kind") if command else None,
        command_run_id=command_run_id(entry) if command else None,
        internal_continuation=_is_internal_continuation(entry) if command else False,
    )
