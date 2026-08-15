"""Durable terminal-synthesis reconstruction (W5-DSH-01, Wave 5 Gate 2).

The guard must recognize the real terminal-synthesis triggers (plain
provisional final, validator rejection, no-progress convergence) and replay
the harness's evidence-before-terminal precedence and progress rule from
durable events only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.plans import SessionPlan
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.attempt_result import update_observation_progress
from agent_core.harness.completion_blocking import current_task_plan
from agent_core.harness.completion_evidence import (
    evaluate_context_completion_evidence,
    persisted_completion_evidence_events,
)
from agent_core.harness.concurrent_batch import DEFAULT_REPEAT_HARD_STOP_THRESHOLD
from agent_core.harness.models import HarnessAttempt, HarnessContext, HarnessEventDraft, HarnessTask


@dataclass(frozen=True)
class _BatchScan:
    tool_names: tuple[str, ...]
    validator_rejection: bool
    state_changed: bool
    observations: tuple[tuple[ToolCall, ToolResult], ...]
    end_index: int


@dataclass(frozen=True)
class _TerminalSynthesisState:
    pending: bool
    plain_provisional: bool
    validator_rejection: bool
    no_progress_count: int


def _scan_attempt_batches(
    events: list[SessionEvent],
    attempt_number: int,
    created_at: datetime,
) -> list[_BatchScan]:
    """One scan record per durable model response (its tool batch), with the
    proposed tool names, the validator-rejection signal and the executed
    (tool_call, tool_result) observations the harness's progress replay
    consumes."""
    batches: list[_BatchScan] = []
    index = 0
    while index < len(events):
        event = events[index]
        index += 1
        if (
            event.event_type is not EventType.MODEL_RESPONSE_RECEIVED
            or event.payload.get("attempt_number") != attempt_number
        ):
            continue
        tool_names: list[str] = []
        payload_names = event.payload.get("proposed_tool_names")
        if isinstance(payload_names, list | tuple):
            tool_names.extend(
                name
                for name in payload_names
                if isinstance(name, str) and name.strip()
            )
        validator_rejection = False
        state_changed = False
        observations: list[tuple[ToolCall, ToolResult]] = []
        while index < len(events) and events[index].event_type not in {
            EventType.MODEL_RESPONSE_RECEIVED,
            EventType.ATTEMPT_OUTCOME_RECORDED,
        }:
            following = events[index]
            index += 1
            if following.event_type is EventType.TOOL_CALL_PROPOSED:
                name = following.payload.get("tool_name")
                if isinstance(name, str) and name.strip():
                    tool_names.append(name.strip())
            elif following.event_type in {
                EventType.TOOL_EXECUTION_COMPLETED,
                EventType.TOOL_EXECUTION_FAILED,
            }:
                if _validator_failed_event(following.payload):
                    validator_rejection = True
                observation = _execution_observation(following.payload, created_at)
                if observation is not None:
                    observations.append(observation)
            elif following.event_type in {
                EventType.PLAN_UPDATED,
                EventType.APPROVAL_REQUESTED,
            }:
                state_changed = True
        batches.append(
            _BatchScan(
                tool_names=tuple(dict.fromkeys(tool_names)),
                validator_rejection=validator_rejection,
                state_changed=state_changed,
                observations=tuple(observations),
                end_index=index,
            )
        )
    return batches


def _execution_observation(
    payload: dict[str, object],
    created_at: datetime,
) -> tuple[ToolCall, ToolResult] | None:
    """The (tool_call, tool_result) pair of one durable tool execution, so
    the no-progress counter is replayed through the harness's own shared
    update_observation_progress transition."""
    raw_id = payload.get("tool_call_id")
    name = payload.get("tool_name")
    if not isinstance(raw_id, str) or not isinstance(name, str) or not name.strip():
        return None
    try:
        tool_call_id = ToolCallId(UUID(raw_id))
    except ValueError:
        return None
    status_value = payload.get("status")
    if isinstance(status_value, str):
        try:
            status = ToolCallStatus(status_value)
        except ValueError:
            status = ToolCallStatus.FAILED
    else:
        status = ToolCallStatus.FAILED
    raw_metadata = payload.get("metadata")
    metadata: dict[str, object] = raw_metadata if isinstance(raw_metadata, dict) else {}
    return (
        ToolCall(
            tool_call_id=tool_call_id,
            name=name,
            arguments={},
            created_at=created_at,
        ),
        ToolResult(
            tool_call_id=tool_call_id,
            status=status,
            output=str(payload.get("output") or ""),
            metadata=dict(metadata),
        ),
    )


def _no_progress_counter(batches: list[_BatchScan]) -> int:
    metadata: dict[str, object] = {}
    for batch in batches:
        metadata = update_observation_progress(
            metadata,
            batch.observations,
            state_changed=batch.state_changed,
            threshold=DEFAULT_REPEAT_HARD_STOP_THRESHOLD,
        )
    count = metadata.get("consecutive_no_progress_batches", 0)
    return count if isinstance(count, int) and not isinstance(count, bool) else 0


def _terminal_synthesis_state(
    batches: list[_BatchScan],
    events: list[SessionEvent],
    attempt_number: int,
    *,
    task: HarnessTask,
    session: Session,
    created_at: datetime,
    evidence_missing: bool,
) -> _TerminalSynthesisState:
    no_progress_count = _no_progress_counter(batches)
    # The harness's terminal-synthesis flags persist in the batch metadata:
    # a validator rejection (or a reached no-progress threshold) keeps the
    # terminal entry pending until the evidence gate returns None, so the
    # trigger is any batch in the attempt, not only the last one.
    validator_rejection = any(batch.validator_rejection for batch in batches)
    no_progress_triggered = no_progress_count >= DEFAULT_REPEAT_HARD_STOP_THRESHOLD
    last_response_index: int | None = None
    for index, event in enumerate(events):
        if (
            event.event_type is EventType.MODEL_RESPONSE_RECEIVED
            and event.payload.get("attempt_number") == attempt_number
        ):
            last_response_index = index
    plain_provisional = False
    if last_response_index is not None:
        last_response = events[last_response_index]
        tool_call_count = last_response.payload.get("tool_call_count", 0)
        plain = (
            isinstance(tool_call_count, int)
            and not isinstance(tool_call_count, bool)
            and tool_call_count == 0
        )
        no_tools_follow = not any(
            event.event_type
            in {
                EventType.TOOL_CALL_PROPOSED,
                EventType.TOOL_EXECUTION_STARTED,
                EventType.TOOL_EXECUTION_COMPLETED,
                EventType.TOOL_EXECUTION_FAILED,
            }
            for event in events[last_response_index + 1 :]
        )
        plan_blocked = (
            task.plan_required
            and not _durable_plan(events, task, session, created_at).steps
        )
        plain_provisional = (
            last_response.payload.get("response_stage") == "tool_loop"
            and plain
            and no_tools_follow
            and not plan_blocked
        )
    # Runtime precedence: _request_terminal_synthesis runs
    # prepare_terminal_synthesis_evidence FIRST and returns immediately when
    # completion evidence is missing (typed correction or failure). Terminal
    # synthesis - and its validator/no-progress/final-answer guidance - can
    # only be pending after evidence handling is satisfied.
    pending = (
        plain_provisional or validator_rejection or no_progress_triggered
    ) and not evidence_missing
    return _TerminalSynthesisState(
        pending=pending,
        plain_provisional=plain_provisional,
        validator_rejection=validator_rejection,
        no_progress_count=no_progress_count,
    )


def _durable_plan(
    events: list[SessionEvent],
    task: HarnessTask,
    session: Session,
    created_at: datetime,
) -> SessionPlan:
    return current_task_plan(
        HarnessContext(
            task=task,
            session=session,
            attempt=HarnessAttempt(number=1, started_at=created_at),
            completion_evidence_events=(),
        ),
        tuple(
            HarnessEventDraft(
                event_type=event.event_type,
                actor=event.actor,
                payload=event.payload,
            )
            for event in events
            if event.event_type is EventType.PLAN_UPDATED
        ),
    )


def _validator_failed_event(payload: dict[str, object]) -> bool:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return False
    tags = metadata.get("tool_tags")
    if not (isinstance(tags, list) and "validator" in tags):
        return False
    if payload.get("status") != ToolCallStatus.EXECUTED.value:
        return True
    outcome = metadata.get("validator_outcome")
    if isinstance(outcome, str):
        return outcome != "passed"
    result = metadata.get("validator_result")
    return isinstance(result, dict) and result.get("passed") is False


def terminal_synthesis_pending(
    events: list[SessionEvent],
    attempt_number: int,
    *,
    task: HarnessTask,
    session: Session,
    created_at: datetime,
    full_stream: list[SessionEvent],
) -> bool:
    """True only when the next dispatch is the terminal-synthesis dispatch.

    The harness schedules terminal synthesis after a PLAIN response staged
    as a provisional final, after a validator rejection, or after the
    no-progress convergence threshold (replayed with the harness's own
    progress rule). The required-plan nudge path is never terminal
    synthesis, and missing completion evidence takes precedence: the next
    dispatch is the typed evidence correction (or a failure), never
    terminal synthesis."""
    status = evaluate_context_completion_evidence(
        HarnessContext(
            task=task,
            session=session,
            attempt=HarnessAttempt(number=attempt_number, started_at=created_at),
            completion_evidence_events=persisted_completion_evidence_events(
                full_stream
            ),
        ),
        (),
    )
    state = _terminal_synthesis_state(
        _scan_attempt_batches(events, attempt_number, created_at),
        events,
        attempt_number,
        task=task,
        session=session,
        created_at=created_at,
        evidence_missing=not status.satisfied,
    )
    return state.pending
