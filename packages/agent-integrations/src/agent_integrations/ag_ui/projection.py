"""Pure, replayable projection from Zebra Events to AG-UI events.

The projector only reads immutable ``SessionEvent`` values. It deliberately
does not know about HTTP, SSE, Event Store writes, Host transport or Trench.
Those concerns belong to later adapters and can consume this stable contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ag_ui.core import (
    Event,
    Interrupt,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from agent_core.domain.events import EventType, SessionEvent

from agent_integrations.ag_ui.client_effect_projection import project_client_effect
from agent_integrations.ag_ui.contracts import (
    AgUiCursor,
    AgUiProjection,
    AgUiProjectionError,
    AgUiRunIdentity,
)
from agent_integrations.ag_ui.interrupts import (
    RunFinishedInterruptOutcome,
    project_interrupt_event,
)


@dataclass(slots=True)
class _ProjectionState:
    text_messages: dict[str, str] = field(default_factory=dict)
    text_ended: set[str] = field(default_factory=set)
    tool_calls: set[str] = field(default_factory=set)
    open_interrupts: dict[str, Interrupt] = field(default_factory=dict)
    # ADR-026: once a Turn finished the AG-UI run, the next human message
    # starts a fresh run and the trailing Segment terminal must not emit a
    # second RUN_FINISHED.
    turn_finished: bool = False


class AgUiProjector:
    """Project a complete ordered durable stream or a validated reconnect tail."""

    def project(
        self,
        events: Sequence[SessionEvent],
        identity: AgUiRunIdentity,
        *,
        after: AgUiCursor | str | None = None,
    ) -> AgUiProjection:
        ordered = tuple(events)
        self._validate_stream(ordered, identity)
        cursor = self._decode_cursor(after)
        start_sequence = self._validate_cursor(cursor, ordered, identity)
        state = _ProjectionState()
        projected: list[Event] = []
        for event in ordered:
            projected_for_event = self._project_event(event, identity, state)
            if cursor is None or event.sequence > start_sequence:
                projected.extend(projected_for_event)
        if ordered and cursor is None:
            projected.insert(
                0,
                RunStartedEvent(
                    thread_id=identity.thread_id,
                    run_id=identity.run_id,
                    parent_run_id=identity.parent_run_id,
                ),
            )
        next_cursor = (
            AgUiCursor(
                thread_id=identity.thread_id,
                run_id=identity.run_id,
                sequence=ordered[-1].sequence,
                event_id=str(ordered[-1].event_id),
            )
            if ordered
            else cursor
        )
        return AgUiProjection(tuple(projected), next_cursor, cursor)

    @staticmethod
    def _decode_cursor(after: AgUiCursor | str | None) -> AgUiCursor | None:
        if after is None or isinstance(after, AgUiCursor):
            return after
        return AgUiCursor.decode(after)

    @staticmethod
    def _validate_stream(events: tuple[SessionEvent, ...], identity: AgUiRunIdentity) -> None:
        previous_sequence = -1
        seen_ids: set[str] = set()
        for event in events:
            if event.session_id != identity.session_id:
                raise AgUiProjectionError("projection contains a different durable session")
            event_id = str(event.event_id)
            if event.sequence <= previous_sequence or event_id in seen_ids:
                raise AgUiProjectionError("durable events must have unique increasing sequences")
            previous_sequence = event.sequence
            seen_ids.add(event_id)

    @staticmethod
    def _validate_cursor(
        cursor: AgUiCursor | None,
        events: tuple[SessionEvent, ...],
        identity: AgUiRunIdentity,
    ) -> int:
        if cursor is None:
            return -1
        if cursor.thread_id != identity.thread_id or cursor.run_id != identity.run_id:
            raise AgUiProjectionError("cursor does not match the requested Task/run")
        matched = next((event for event in events if event.sequence == cursor.sequence), None)
        if matched is None or str(matched.event_id) != cursor.event_id:
            raise AgUiProjectionError("cursor does not match an exact durable Event")
        return cursor.sequence

    def _project_event(
        self,
        event: SessionEvent,
        identity: AgUiRunIdentity,
        state: _ProjectionState,
    ) -> tuple[Event, ...]:
        timestamp = int(event.created_at.timestamp() * 1000)
        payload = event.payload
        client_effect = project_client_effect(event, timestamp=timestamp)
        if client_effect is not None:
            return client_effect
        if event.event_type is EventType.MODEL_RESPONSE_DELTA:
            model_call_id = _required_payload_text(payload, "model_call_id")
            delta = _required_payload_text(payload, "content_delta", allow_empty=True)
            message_id = state.text_messages.get(model_call_id)
            start: tuple[Event, ...] = ()
            if message_id is None:
                message_id = f"message:{model_call_id}"
                state.text_messages[model_call_id] = message_id
                start = (TextMessageStartEvent(timestamp=timestamp, message_id=message_id),)
            if message_id in state.text_ended:
                raise AgUiProjectionError("text delta follows a terminal message")
            return start + (
                TextMessageContentEvent(timestamp=timestamp, message_id=message_id, delta=delta),
            )
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
            model_call_id = _optional_payload_text(payload, "model_call_id") or str(event.event_id)
            message_id = state.text_messages.get(model_call_id)
            had_message = message_id is not None
            assistant_message = _optional_payload_text(payload, "assistant_message")
            if assistant_message == "Tool calls proposed." and not had_message:
                return ()
            output: list[Event] = []
            if message_id is None:
                message_id = f"message:{model_call_id}"
                state.text_messages[model_call_id] = message_id
                output.append(TextMessageStartEvent(timestamp=timestamp, message_id=message_id))
            if (
                assistant_message is not None
                and not had_message
                and model_call_id not in state.text_ended
            ):
                output.append(
                    TextMessageContentEvent(
                        timestamp=timestamp, message_id=message_id, delta=assistant_message
                    )
                )
            if model_call_id not in state.text_ended:
                output.append(TextMessageEndEvent(timestamp=timestamp, message_id=message_id))
                state.text_ended.add(model_call_id)
            return tuple(output)
        if event.event_type is EventType.TOOL_CALL_PROPOSED:
            call_id = _required_payload_text(payload, "tool_call_id")
            tool_name = _required_payload_text(payload, "tool_name")
            arguments = payload.get("arguments", {})
            if not isinstance(arguments, Mapping):
                raise AgUiProjectionError("tool arguments must be an object")
            state.tool_calls.add(call_id)
            return (
                ToolCallStartEvent(
                    timestamp=timestamp,
                    tool_call_id=call_id,
                    tool_call_name=tool_name,
                ),
                ToolCallArgsEvent(
                    timestamp=timestamp,
                    tool_call_id=call_id,
                    delta=_json_text(arguments),
                ),
            )
        if event.event_type in {
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
        }:
            call_id = _required_payload_text(payload, "tool_call_id")
            if call_id not in state.tool_calls:
                raise AgUiProjectionError("tool result has no preceding proposal")
            tool_output = _required_payload_text(payload, "output", allow_empty=True)
            result_id = f"tool-result:{call_id}"
            state.tool_calls.remove(call_id)
            return (
                ToolCallEndEvent(timestamp=timestamp, tool_call_id=call_id),
                ToolCallResultEvent(
                    timestamp=timestamp,
                    message_id=result_id,
                    tool_call_id=call_id,
                    content=_tool_result_content(payload, tool_output),
                    role="tool",
                ),
            )
        if event.event_type is EventType.TASK_PREPARED:
            return (
                StateSnapshotEvent(
                    timestamp=timestamp,
                    snapshot={"task": {"title": _required_payload_text(payload, "title")}},
                ),
            )
        if event.event_type is EventType.PLAN_UPDATED:
            steps = payload.get("steps")
            if not isinstance(steps, list):
                raise AgUiProjectionError("plan update steps must be an array")
            return (
                StateDeltaEvent(
                    timestamp=timestamp,
                    delta=[{"op": "replace", "path": "/plan/steps", "value": steps}],
                ),
            )
        if event.event_type in {EventType.APPROVAL_REQUESTED, EventType.CLARIFICATION_REQUESTED}:
            return project_interrupt_event(event, identity, state.open_interrupts, timestamp)
        if event.event_type is EventType.USER_MESSAGE_RECEIVED:
            if state.turn_finished and _optional_payload_text(payload, "turn_id") is not None:
                state.turn_finished = False
                return (
                    RunStartedEvent(
                        thread_id=identity.thread_id,
                        run_id=identity.run_id,
                        parent_run_id=identity.parent_run_id,
                        timestamp=timestamp,
                    ),
                )
            return ()
        if event.event_type is EventType.TURN_COMPLETED:
            state.turn_finished = True
            return (
                RunFinishedEvent(
                    timestamp=timestamp,
                    thread_id=identity.thread_id,
                    run_id=identity.run_id,
                    outcome=RunFinishedSuccessOutcome(),
                ),
            )
        if event.event_type is EventType.TURN_CANCELLED:
            # Control-plane cancellation closes the AG-UI run like an
            # interrupt: without a terminal the client would hang on an
            # unfinished run (ADR-026 §6).
            state.turn_finished = True
            turn_id = _optional_payload_text(payload, "turn_id") or str(event.event_id)
            return (
                RunFinishedEvent(
                    timestamp=timestamp,
                    thread_id=identity.thread_id,
                    run_id=identity.run_id,
                    outcome=RunFinishedInterruptOutcome(
                        interrupts=[
                            Interrupt(
                                id=f"turn-cancelled:{turn_id}",
                                reason=(
                                    _optional_payload_text(payload, "reason")
                                    or "session_cancelled"
                                ),
                            )
                        ]
                    ),
                ),
            )
        if event.event_type is EventType.TURN_FAILED:
            state.turn_finished = True
            message = (
                _optional_payload_text(payload, "reason")
                or _optional_payload_text(payload, "summary")
                or "Zebra turn failed"
            )
            return (
                RunErrorEvent(timestamp=timestamp, message=message, code="zebra_turn_failed"),
            )
        if event.event_type is EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED:
            state.turn_finished = True
            return (
                RunErrorEvent(
                    timestamp=timestamp,
                    message=(
                        "The workspace changed while the conversation was resuming. "
                        "Retry the request."
                    ),
                    code="zebra_handoff_workspace_drift",
                ),
            )
        if event.event_type is EventType.SESSION_FAILED:
            if state.turn_finished:
                return ()
            message = (
                _optional_payload_text(payload, "summary")
                or _optional_payload_text(payload, "reason")
                or "Zebra session failed"
            )
            return (
                RunErrorEvent(timestamp=timestamp, message=message, code="zebra_session_failed"),
            )
        if event.event_type is EventType.SESSION_COMPLETED:
            if state.turn_finished:
                return ()
            return (
                RunFinishedEvent(
                    timestamp=timestamp,
                    thread_id=identity.thread_id,
                    run_id=identity.run_id,
                    outcome=RunFinishedSuccessOutcome(),
                ),
            )
        return ()


def _required_payload_text(
    payload: Mapping[str, Any], key: str, *, allow_empty: bool = False
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise AgUiProjectionError(f"durable payload field {key!r} must be text")
    if not allow_empty and not value.strip():
        raise AgUiProjectionError(f"durable payload field {key!r} must not be blank")
    return value


def _optional_payload_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _json_text(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise AgUiProjectionError("tool arguments are not JSON serializable") from exc


def _tool_result_content(payload: Mapping[str, Any], output: str) -> str:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("delivery") is not True:
        return output
    artifact_uri = metadata.get("artifact_uri")
    file_name = metadata.get("file_name")
    mime_type = metadata.get("mime_type")
    size_bytes = metadata.get("size_bytes")
    status = payload.get("status")
    if not (
        isinstance(artifact_uri, str)
        and artifact_uri.startswith("artifact://")
        and isinstance(file_name, str)
        and file_name
        and isinstance(mime_type, str)
        and mime_type
        and isinstance(size_bytes, int)
        and size_bytes >= 0
        and isinstance(status, str)
        and status
    ):
        return output
    return _json_text(
        {
            "artifact": {
                "file_name": file_name,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "uri": artifact_uri,
            },
            "output": output,
            "status": status,
            "type": "zebra.user_file.v1",
        }
    )
