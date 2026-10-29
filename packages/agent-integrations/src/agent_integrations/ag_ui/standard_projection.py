"""Opt-in AG-UI 1.0 public producer; legacy projection is deliberately unchanged."""

from collections.abc import Iterator, Mapping, Sequence
from hashlib import sha256

from ag_ui.core import (
    Event,
    RunErrorEvent,
    RunFinishedCancelledOutcome,
    RunFinishedEvent,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateSnapshotEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from agent_core.domain.events import EventType, SessionEvent

from agent_integrations.ag_ui.activity_projection import activity, project_activity
from agent_integrations.ag_ui.content_parts import project_content_parts
from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.coverage_projection import project_coverage
from agent_integrations.ag_ui.payload_validation import json_text, required_payload_text
from agent_integrations.ag_ui.projection import AgUiProjector
from agent_integrations.ag_ui.projection_state import ProjectionState
from agent_integrations.ag_ui.standard_interrupts import (
    execution_patch,
    input_or_pause,
    standard_public_event,
)
from agent_integrations.ag_ui.standard_public_text import close_public_messages, public_text
from agent_integrations.ag_ui.standard_state import StandardProjectionState
from agent_integrations.ag_ui.standard_subagents import subagent_events
from agent_integrations.ag_ui.standard_usage import record_usage, terminal_usage
from agent_integrations.ag_ui.tool_result_projection import tool_result_content
from agent_integrations.coverage_public_events import (
    strict_coverage_events,
)


class StandardAgUiProjector(AgUiProjector):
    def project_events(
        self,
        events: Sequence[SessionEvent],
        identity: AgUiRunIdentity,
        *,
        state: ProjectionState | None = None,
        strict_coverage: bool = False,
    ) -> Iterator[tuple[SessionEvent, tuple[Event, ...]]]:
        ordered = tuple(events)
        self._validate_stream(ordered, identity)
        if state is None:
            state = StandardProjectionState()
        if not isinstance(state, StandardProjectionState):
            raise AgUiProjectionError("standard profile requires independent state")
        state.bind(identity)
        if state.protocol_run_id is None:
            state.protocol_run_id = identity.run_id
        strict = strict_coverage or state.strict_coverage or strict_coverage_events(ordered)
        state.strict_coverage = strict
        if ordered and ordered[0].sequence <= state.last_sequence:
            raise AgUiProjectionError("durable events must have unique increasing sequences")
        for event in ordered:
            public = standard_public_event(event, strict=strict)
            frames: tuple[Event, ...] = ()
            if public is not None and state.turn_finished:
                status = {
                    EventType.TURN_COMPLETED: "completed",
                    EventType.SESSION_COMPLETED: "completed",
                    EventType.TURN_CANCELLED: "cancelled",
                    EventType.SESSION_CANCELLED: "cancelled",
                    EventType.TURN_FAILED: "failed",
                    EventType.SESSION_FAILED: "failed",
                }.get(public.event_type)
                if status is not None:
                    state.public_execution = {"status": status}
            if public is not None and not state.turn_finished:
                coverage = project_coverage(
                    public, state.coverage_runs, timestamp=int(public.created_at.timestamp() * 1000)
                )
                frames = (
                    (coverage,)
                    if coverage is not None
                    else self._standard_event(
                        public,
                        identity,
                        state,
                    )
                )
            if state.turn_finished and state.commentary_open:
                index = next(
                    (
                        i
                        for i, frame in enumerate(frames)
                        if isinstance(frame, RunFinishedEvent | RunErrorEvent)
                    ),
                    len(frames),
                )
                frames = (
                    *frames[:index],
                    *close_public_messages(state, int(event.created_at.timestamp() * 1000)),
                    *frames[index:],
                )
            if not state.started:
                frames = (
                    RunStartedEvent(
                        protocol_version="1.0",
                        timestamp=int(event.created_at.timestamp() * 1000),
                        thread_id=identity.thread_id,
                        run_id=state.protocol_run_id,
                        metadata={
                            "zebra": {
                                "version": 1,
                                "previousProtocolRunId": state.previous_protocol_run_id,
                            }
                        }
                        if state.previous_protocol_run_id is not None
                        else None,
                    ),
                    StateSnapshotEvent(
                        snapshot={"execution": dict(state.public_execution)}
                        if state.public_execution
                        else {}
                    ),
                    *frames,
                )
                state.started = True
            state.last_sequence = event.sequence
            yield event, frames

    def _standard_event(
        self,
        event: SessionEvent,
        identity: AgUiRunIdentity,
        state: StandardProjectionState,
    ) -> tuple[Event, ...]:
        kind, payload = event.event_type, event.payload
        timestamp = int(event.created_at.timestamp() * 1000)
        if kind in {EventType.PUBLIC_OUTPUT, EventType.ANSWER_COMMITTED}:
            return public_text(event, state)
        if kind is EventType.MODEL_RESPONSE_RECEIVED:
            return record_usage(payload, state, timestamp, fallback_call_id=str(event.event_id))
        if kind is EventType.MODEL_RESPONSE_DELTA:
            return ()  # No durable publication classification exists on candidate deltas.
        if kind is EventType.TOOL_CALL_PROPOSED:
            call = required_payload_text(payload, "tool_call_id")
            name = required_payload_text(payload, "tool_name")
            arguments = payload.get("arguments")
            if not isinstance(arguments, Mapping):
                raise AgUiProjectionError("tool arguments must be a complete object")
            if call in state.pending_tools:
                raise AgUiProjectionError("duplicate tool proposal")
            state.pending_tools[call] = name
            return (
                ToolCallStartEvent(
                    timestamp=timestamp,
                    tool_call_id=call,
                    tool_call_name=name,
                    parent_message_id="tool-message:"
                    + sha256((str(state.protocol_run_id) + "\0" + call).encode()).hexdigest(),
                ),
                ToolCallArgsEvent(
                    timestamp=timestamp,
                    tool_call_id=call,
                    delta=json_text(arguments, allow_nan=False),
                ),
                ToolCallEndEvent(timestamp=timestamp, tool_call_id=call),
            )
        if kind in {EventType.TOOL_EXECUTION_COMPLETED, EventType.TOOL_EXECUTION_FAILED}:
            call = required_payload_text(payload, "tool_call_id")
            if call not in state.pending_tools:
                raise AgUiProjectionError("tool result has no proposal in this protocol slice")
            state.pending_tools.pop(call)
            state.executing_tools.discard(call)
            output = required_payload_text(payload, "output", allow_empty=True)
            return (
                activity(
                    "execution:" + call,
                    "tool_execution",
                    {
                        "tool_call_id": call,
                        "status": "failed"
                        if kind is EventType.TOOL_EXECUTION_FAILED
                        else "completed",
                    },
                    timestamp,
                ),
                ToolCallResultEvent(
                    timestamp=timestamp,
                    message_id="tool-result:" + call,
                    tool_call_id=call,
                    content=tool_result_content(payload, output),
                    role="tool",
                ),
                *project_content_parts(payload, tool_call_id=call, timestamp=timestamp),
            )
        activities = project_activity(event, state)
        if activities:
            return activities
        children = subagent_events(event, state, identity.thread_id)
        if children:
            return children
        pause = input_or_pause(event, identity, state)
        if pause:
            return pause
        if kind in {
            EventType.TURN_FAILED,
            EventType.SESSION_FAILED,
        }:
            state.turn_finished = True
            return (
                execution_patch(state, {"status": "failed"}, timestamp),
                RunErrorEvent(
                    timestamp=timestamp,
                    message="Agent execution failed",
                    code="zebra_execution_failed",
                    usage=terminal_usage(state),
                ),
            )
        if kind in {
            EventType.TURN_COMPLETED,
            EventType.SESSION_COMPLETED,
            EventType.TURN_CANCELLED,
            EventType.SESSION_CANCELLED,
        }:
            state.turn_finished = True
            cancelled = kind in {EventType.TURN_CANCELLED, EventType.SESSION_CANCELLED}
            return (
                execution_patch(
                    state, {"status": "cancelled" if cancelled else "completed"}, timestamp
                ),
                RunFinishedEvent(
                    timestamp=timestamp,
                    thread_id=identity.thread_id,
                    run_id=str(state.protocol_run_id),
                    outcome=RunFinishedCancelledOutcome()
                    if cancelled
                    else RunFinishedSuccessOutcome(),
                    usage=terminal_usage(state),
                ),
            )
        return ()
