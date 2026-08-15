"""Durable attempt chain validation and epoch scoping (Wave 5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from agent_core.domain.agent_tasks import ExecutionSegment, RolloverReason
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessAttempt
from agent_core.ports.agent_tasks import TaskEvent


class AttemptReconstructionError(ValueError):
    """The durable attempt stream cannot be reconstructed safely."""


def usage_int(metadata: dict[str, object], key: str, default: int) -> int:
    value = metadata.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def durable_usage(events: list[SessionEvent]) -> tuple[int, int]:
    """Cumulative model/tool usage from durable attempt outcomes."""
    model_calls = 0
    tool_calls = 0
    for event in events:
        if event.event_type is not EventType.ATTEMPT_OUTCOME_RECORDED:
            continue
        raw = event.payload.get("result_metadata")
        if not isinstance(raw, dict):
            continue
        model_calls += usage_int(raw, "model_calls_used", 0)
        tool_calls += usage_int(raw, "tool_calls_executed", 0)
    return model_calls, tool_calls


def remaining_budget(budget: int | None, used: int) -> int | None:
    if budget is None:
        return None
    return max(0, budget - used)


def epoch_scoped_events(
    task_events: list[TaskEvent],
    segments: tuple[ExecutionSegment, ...] = (),
) -> list[SessionEvent]:
    """Scope attempt facts to the active logical epoch.

    Only an authoritative TERMINAL_FOLLOW_UP Segment reason starts a new
    attempt epoch: attempt facts from earlier segments must not drive
    retry/recovery of the follow-up. A plain user message inside an active
    Attempt is a Turn, not a new Attempt - it must not reset the epoch.
    Non-terminal rollovers (context/recovery/agent hint) stay inside the same
    epoch, preserving attempt identity across segments.
    """
    boundary = 0
    terminal_segments = [
        segment
        for segment in segments
        if segment.rollover_reason is RolloverReason.TERMINAL_FOLLOW_UP
    ]
    if terminal_segments:
        latest = max(terminal_segments, key=lambda segment: segment.segment_index)
        segment_sequences = [
            item.task_sequence for item in task_events if item.segment_id == latest.session_id
        ]
        if segment_sequences:
            boundary = min(segment_sequences)
    return [item.event for item in task_events if item.task_sequence >= boundary]


def derive_epoch_coordinates(
    task_events: list[TaskEvent],
    segments: tuple[ExecutionSegment, ...] = (),
) -> tuple[int, str]:
    """(epoch_sequence, turn_id) for the active logical epoch. The epoch
    sequence derives from the latest TERMINAL_FOLLOW_UP segment index; the
    Turn is the latest plain durable user message of the epoch."""
    terminal_segments = [
        segment
        for segment in segments
        if segment.rollover_reason is RolloverReason.TERMINAL_FOLLOW_UP
    ]
    epoch_sequence = 0
    if terminal_segments:
        epoch_sequence = max(segment.segment_index for segment in terminal_segments) + 1
    return epoch_sequence, derive_turn_id(task_events, segments)


def derive_turn_id(
    task_events: list[TaskEvent],
    segments: tuple[ExecutionSegment, ...] = (),
) -> str:
    """Stable active-epoch Turn identity derived from the durable user-message
    fact. The Turn is the latest plain user message of the epoch; it survives
    non-terminal handoffs (handoff-carried messages are not Turns) and only
    advances on a genuine terminal follow-up."""
    scoped = epoch_scoped_events(task_events, segments)
    scoped_ids = {event.event_id for event in scoped}
    plain: SessionEvent | None = None
    first_user: SessionEvent | None = None
    for item in task_events:
        if item.event.event_id not in scoped_ids:
            continue
        if item.event.event_type is not EventType.USER_MESSAGE_RECEIVED:
            continue
        if first_user is None:
            first_user = item.event
        if item.event.payload.get("source") != "session_handoff":
            plain = item.event
    selected = plain or first_user
    if selected is not None:
        return f"turn:{selected.event_id}"
    return "turn:root"


def mirror_attempt_messages(
    events: list[SessionEvent],
    *,
    attempt_number: int,
    created_at: datetime,
    provider_events: list[SessionEvent] | None = None,
) -> tuple[SessionMessage, ...]:
    """Mirror the in-attempt assistant/tool messages the harness appends to
    the actual request: assistant messages carry their tool calls from
    TOOL_CALL_PROPOSED (name/id/arguments/provider call id), and tool-result
    messages use the harness's own ``tool_result_content`` serialization with
    the same provider-or-internal call id rule as ``append_tool_result``.

    ``provider_events`` optionally supplies the full durable stream so the
    provider-call-id mapping is seeded from proposals that precede a
    continuation snapshot boundary (the tail events alone would lose the
    mapping for approved/clarified calls)."""
    from agent_core.harness.tool_result_message import (
        tool_result_content,
        tool_result_status,
    )

    messages: list[SessionMessage] = []
    provider_ids: dict[str, str] = {}
    for event in provider_events if provider_events is not None else events:
        if event.payload.get("attempt_number") != attempt_number:
            continue
        if event.event_type is EventType.TOOL_CALL_PROPOSED:
            raw_id = event.payload.get("tool_call_id")
            provider_call_id = event.payload.get("provider_call_id")
            if isinstance(raw_id, str) and isinstance(provider_call_id, str):
                provider_ids[raw_id] = provider_call_id
    index = 0
    while index < len(events):
        event = events[index]
        index += 1
        if event.payload.get("attempt_number") != attempt_number:
            continue
        if event.event_type is EventType.TOOL_CALL_PROPOSED:
            raw_id = event.payload.get("tool_call_id")
            provider_call_id = event.payload.get("provider_call_id")
            if isinstance(raw_id, str) and isinstance(provider_call_id, str):
                provider_ids[raw_id] = provider_call_id
        elif event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
            content = event.payload.get("assistant_message")
            tool_calls: list[ToolCall] = []
            while index < len(events) and events[index].event_type not in {
                EventType.MODEL_RESPONSE_RECEIVED,
                EventType.TOOL_EXECUTION_STARTED,
                EventType.TOOL_EXECUTION_COMPLETED,
                EventType.TOOL_EXECUTION_FAILED,
                EventType.ATTEMPT_OUTCOME_RECORDED,
            }:
                proposed = events[index]
                if (
                    proposed.event_type is EventType.TOOL_CALL_PROPOSED
                    and proposed.payload.get("attempt_number") == attempt_number
                ):
                    raw_id = proposed.payload.get("tool_call_id")
                    name = proposed.payload.get("tool_name")
                    arguments = proposed.payload.get("arguments")
                    provider_call_id = proposed.payload.get("provider_call_id")
                    provider_tool_name = proposed.payload.get("provider_tool_name")
                    provider_arguments = proposed.payload.get("provider_arguments")
                    if (
                        isinstance(raw_id, str)
                        and isinstance(name, str)
                        and name.strip()
                        and isinstance(arguments, dict)
                    ):
                        try:
                            tool_call_id = ToolCallId(UUID(raw_id))
                        except ValueError as exc:
                            raise AttemptReconstructionError(
                                f"invalid tool call id: {exc}"
                            ) from exc
                        if provider_call_id is not None and not isinstance(provider_call_id, str):
                            raise AttemptReconstructionError("provider tool call id must be text")
                        if (
                            (provider_tool_name is None) != (provider_arguments is None)
                            or (
                                provider_tool_name is not None
                                and not isinstance(provider_tool_name, str)
                            )
                            or (
                                provider_arguments is not None
                                and not isinstance(provider_arguments, dict)
                            )
                        ):
                            raise AttemptReconstructionError(
                                "provider tool presentation is incomplete"
                            )
                        if isinstance(provider_call_id, str):
                            provider_ids[raw_id] = provider_call_id
                        tool_calls.append(
                            ToolCall(
                                tool_call_id=tool_call_id,
                                name=name,
                                arguments=arguments,
                                created_at=created_at,
                                provider_call_id=provider_call_id,
                                provider_tool_name=provider_tool_name,
                                provider_arguments=provider_arguments,
                            )
                        )
                index += 1
            # Only responses that were part of a tool exchange are appended to
            # the actual request conversation (append_tool_batch). Plain
            # candidate responses are emitted as events but never re-sent, so
            # mirroring them would break the dispatch reconstruction guard on
            # the next in-attempt completion (e.g. evidence correction).
            if tool_calls:
                messages.append(
                    SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content=content if isinstance(content, str) else "",
                        created_at=created_at,
                        tool_calls=tuple(tool_calls),
                    )
                )
        elif event.event_type in {
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
        }:
            raw_id = str(event.payload.get("tool_call_id", ""))
            try:
                tool_call_id = ToolCallId(UUID(raw_id))
            except ValueError as exc:
                raise AttemptReconstructionError(f"invalid tool call id: {exc}") from exc
            raw_metadata = event.payload.get("metadata")
            metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
            result = ToolResult(
                tool_call_id=tool_call_id,
                status=_tool_status(event.payload.get("status")),
                output=str(event.payload.get("output") or ""),
                metadata=metadata,
            )
            messages.append(
                SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.TOOL,
                    content=tool_result_content(result),
                    created_at=created_at,
                    tool_call_id=provider_ids.get(raw_id, raw_id),
                    metadata={"tool_result_status": tool_result_status(result)},
                )
            )
    return tuple(messages)


def _tool_status(value: object) -> ToolCallStatus:
    if isinstance(value, str):
        try:
            return ToolCallStatus(value)
        except ValueError:
            pass
    return ToolCallStatus.FAILED


def validate_attempt_reconstruction(
    session_events: list[SessionEvent],
    attempt: HarnessAttempt,
    *,
    max_attempts: int | None = None,
    epoch_sequence: int | None = None,
    turn_id: str | None = None,
) -> None:
    """Validate the complete active-epoch causal chain before dispatch:
    ordered start sequences with no duplicates/gaps, stable attempt ids,
    causal references, outcome/start agreement, and retry scheduling."""
    try:
        starts = sorted(
            _start_events(session_events),
            key=lambda event: _start_sequence(event),
        )
        outcomes = sorted(
            _outcome_events(session_events),
            key=lambda event: int(event.payload["attempt_sequence"]),
        )
    except (TypeError, ValueError) as exc:
        raise AttemptReconstructionError(f"malformed attempt coordinate: {exc}") from exc
    previous_sequence = 0
    starts_by_sequence: dict[int, list[SessionEvent]] = {}
    for start in starts:
        sequence = _start_sequence(start)
        starts_by_sequence.setdefault(sequence, []).append(start)
    for sequence in sorted(starts_by_sequence):
        if sequence != previous_sequence + 1:
            raise AttemptReconstructionError("attempt start sequence is duplicated or has a gap")
        previous_sequence = sequence
        if max_attempts is not None and sequence > max_attempts:
            raise AttemptReconstructionError(
                f"attempt start {sequence} exceeds the frozen attempt cap"
            )
        start_events = starts_by_sequence[sequence]
        if len(start_events) > 2:
            raise AttemptReconstructionError(
                f"attempt start {sequence} has more than one duplicate"
            )
        if len(start_events) == 2:
            if (start_events[0].payload.get("attempt_id") is None) == (
                start_events[1].payload.get("attempt_id") is None
            ):
                raise AttemptReconstructionError(f"attempt start {sequence} is duplicated")
        for start in start_events:
            attempt_id = start.payload.get("attempt_id")
            if attempt_id is not None and attempt_id != f"attempt-{sequence}":
                raise AttemptReconstructionError(
                    f"attempt start {sequence} carries a mismatched attempt_id"
                )
            causal = start.payload.get("causal_attempt_id")
            expected_causal = f"attempt-{sequence - 1}" if sequence > 1 else None
            if causal is not None and causal != expected_causal:
                raise AttemptReconstructionError(
                    f"attempt start {sequence} carries a mismatched causal reference"
                )
            if attempt_id is not None:
                _require_epoch_coordinates(start.payload, epoch_sequence, turn_id)
                if attempt.number == sequence and attempt_id != attempt.attempt_id:
                    raise AttemptReconstructionError(
                        f"current attempt {sequence} identity does not match the durable start"
                    )
    seen_outcomes: set[int] = set()
    retried: set[int] = set()
    for outcome in outcomes:
        try:
            sequence = int(outcome.payload["attempt_sequence"])
        except (TypeError, ValueError) as exc:
            raise AttemptReconstructionError(f"malformed attempt outcome sequence: {exc}") from exc
        if sequence in seen_outcomes:
            raise AttemptReconstructionError("duplicate attempt outcome recorded")
        seen_outcomes.add(sequence)
        if sequence > previous_sequence or sequence < 1:
            raise AttemptReconstructionError(
                "attempt outcome references an unknown or future attempt"
            )
        attempt_id = outcome.payload.get("attempt_id")
        if attempt_id is not None and attempt_id != f"attempt-{sequence}":
            raise AttemptReconstructionError(
                f"attempt outcome {sequence} carries a mismatched attempt_id"
            )
        if attempt_id is not None:
            _require_epoch_coordinates(outcome.payload, epoch_sequence, turn_id)
        retry_scheduled = bool(outcome.payload.get("retry_scheduled"))
        next_attempt = outcome.payload.get("next_attempt_sequence")
        if retry_scheduled:
            retried.add(sequence)
            if next_attempt != sequence + 1:
                raise AttemptReconstructionError(
                    f"attempt outcome {sequence} retry scheduling is inconsistent"
                )
        elif next_attempt is not None:
            raise AttemptReconstructionError(
                f"attempt outcome {sequence} has a next attempt without retry"
            )
    for start in starts:
        sequence = _start_sequence(start)
        if sequence > 1 and sequence - 1 not in retried:
            raise AttemptReconstructionError(
                f"attempt {sequence} started without a retriable prior outcome"
            )
    for sequence in retried:
        if sequence + 1 > previous_sequence and sequence + 1 != attempt.number:
            raise AttemptReconstructionError(
                f"attempt outcome {sequence} schedules a missing next attempt"
            )
    _validate_model_step_correlation(session_events)
    if attempt.number > 1:
        previous = next(
            (
                outcome
                for outcome in outcomes
                if int(outcome.payload["attempt_sequence"]) == attempt.number - 1
            ),
            None,
        )
        if previous is None or not previous.payload.get("retry_scheduled"):
            raise AttemptReconstructionError(
                f"attempt {attempt.number} has no retriable prior outcome"
            )


def _require_epoch_coordinates(
    payload: dict[str, object],
    epoch_sequence: int | None,
    turn_id: str | None,
) -> None:
    if payload.get("turn_id") is None or payload.get("epoch_sequence") is None:
        raise AttemptReconstructionError(
            "attempt event is missing the durable epoch/turn coordinate"
        )
    if epoch_sequence is not None and payload.get("epoch_sequence") != epoch_sequence:
        raise AttemptReconstructionError(
            "attempt event epoch sequence does not match the active epoch"
        )
    if turn_id is not None and payload.get("turn_id") != turn_id:
        raise AttemptReconstructionError(
            "attempt event turn identity does not match the active epoch"
        )


def _validate_model_step_correlation(session_events: list[SessionEvent]) -> None:
    """A committed MODEL_REQUEST_STARTED must be correlated to a
    MODEL_RESPONSE_RECEIVED with the same model_call_id, unless the attempt is
    durably closed or suspended. A dangling request is an uncertain in-flight
    Step after a crash: fail closed with zero redispatch."""
    responded_calls: set[str] = set()
    closed_attempts: set[int] = set()
    suspended_attempts: set[int] = set()
    for event in session_events:
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED and isinstance(
            event.payload.get("model_call_id"), str
        ):
            responded_calls.add(event.payload["model_call_id"])
        elif event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED and isinstance(
            event.payload.get("attempt_sequence"), int
        ):
            closed_attempts.add(int(event.payload["attempt_sequence"]))
    latest_start_sequence = 0
    for event in session_events:
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED:
            latest_start_sequence = _start_sequence(event)
        elif event.event_type is EventType.SESSION_SUSPENDED:
            if latest_start_sequence:
                suspended_attempts.add(latest_start_sequence)
            payload_number = event.payload.get("attempt_number")
            if isinstance(payload_number, int):
                suspended_attempts.add(payload_number)
    for event in session_events:
        if event.event_type is not EventType.MODEL_REQUEST_STARTED:
            continue
        attempt_number = event.payload.get("attempt_number")
        if isinstance(attempt_number, int) and attempt_number in closed_attempts:
            continue
        if isinstance(attempt_number, int) and attempt_number in suspended_attempts:
            continue
        model_call_id = event.payload.get("model_call_id")
        if not isinstance(model_call_id, str) or not model_call_id.strip():
            raise AttemptReconstructionError(
                "model request step is missing its stable call identity"
            )
        if model_call_id not in responded_calls:
            raise AttemptReconstructionError(
                "model request step has no correlated response; in-flight "
                "provider call state is uncertain"
            )


def _start_events(session_events: list[SessionEvent]) -> list[SessionEvent]:
    return [
        event for event in session_events if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]


def _outcome_events(session_events: list[SessionEvent]) -> list[SessionEvent]:
    return [
        event for event in session_events if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
    ]


def _start_sequence(event: SessionEvent) -> int:
    value = event.payload.get("attempt_sequence") or event.payload.get("attempt_number")
    if value is None:
        raise AttemptReconstructionError("attempt start event lacks a sequence")
    return int(value)
