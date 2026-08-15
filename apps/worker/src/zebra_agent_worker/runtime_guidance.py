"""Durable rebuild of harness runtime guidance (W5-DSH-01, Gate 2).

The actual provider request may contain harness-generated runtime guidance:
missing-evidence observations, required-plan nudges and validator-correction
instructions. These are deterministic functions of the durable evidence/plan
state and the frozen Task facts, so the reconstruction guard rebuilds the
exact messages via the same helpers the harness uses and includes them in the
verified envelope. A tampered observation (content or metadata) therefore
fails closed before any provider call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.plans import SessionPlan
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.attempt_result import (
    append_no_progress_observation,
    observation_fingerprint,
)
from agent_core.harness.capability_guidance import append_required_plan_nudge
from agent_core.harness.completion_blocking import (
    append_missing_evidence_observation,
)
from agent_core.harness.completion_evidence import (
    evaluate_context_completion_evidence,
)
from agent_core.harness.concurrent_batch import DEFAULT_REPEAT_HARD_STOP_THRESHOLD
from agent_core.harness.context_recovery import (
    append_validator_correction_instruction,
)
from agent_core.harness.models import HarnessAttempt, HarnessContext, HarnessEventDraft, HarnessTask


def rebuilt_runtime_guidance(
    events: list[SessionEvent],
    *,
    attempt: HarnessAttempt,
    task: HarnessTask,
    session: Session,
    completion_evidence_events: tuple[HarnessEventDraft, ...],
    created_at: datetime,
    prior_messages: tuple[SessionMessage, ...] = (),
) -> tuple[SessionMessage, ...]:
    """Rebuild the exact runtime guidance messages the actual request
    contains at the next dispatch, derived only from durable state."""
    context = HarnessContext(
        task=task,
        session=session,
        attempt=attempt,
        completion_evidence_events=completion_evidence_events,
    )
    status = evaluate_context_completion_evidence(context, ())
    return _rebuild(
        events,
        attempt_number=attempt.number,
        task=task,
        session=session,
        created_at=created_at,
        missing=status.missing,
        open_plan_steps=status.open_plan_steps,
        evidence_missing=not status.satisfied,
        prior_messages=prior_messages,
    )


def _rebuild(
    events: list[SessionEvent],
    *,
    attempt_number: int,
    task: HarnessTask,
    session: Session,
    created_at: datetime,
    missing: tuple[str, ...],
    open_plan_steps: tuple[str, ...],
    evidence_missing: bool,
    prior_messages: tuple[SessionMessage, ...] = (),
) -> tuple[SessionMessage, ...]:
    guidance: list[SessionMessage] = []
    # A recovered continuation conversation already contains the runtime
    # guidance appended before its snapshot boundary; seed the same state the
    # harness derives from those messages (required_plan_action and
    # completion_evidence_observation_count use exactly these markers).
    evidence_observations = sum(
        1
        for message in prior_messages
        if (message.metadata or {}).get("missing_completion_evidence") is not None
    )
    plan_nudged = any(
        (message.metadata or {}).get("required_plan_nudge") is True
        for message in prior_messages
    )
    validator_instruction_appended = any(
        (message.metadata or {}).get("validator_correction") is True
        for message in prior_messages
    )
    no_progress_observation_appended = any(
        (message.metadata or {}).get("tool_loop_no_progress") is True
        for message in prior_messages
    )
    plan_exists = bool(_durable_plan(events, task, session, created_at).steps)
    batches = _scan_attempt_batches(events, attempt_number, created_at)
    state = _terminal_synthesis_state(
        batches,
        events,
        attempt_number,
        task=task,
        session=session,
        created_at=created_at,
    )

    for batch in batches:
        tool_names = batch.tool_names
        validator_failed = batch.validator_rejection
        if task.plan_required and not plan_exists and not plan_nudged and _nudge_triggered(
            tool_names
        ):
            scratch: list[SessionMessage] = []
            append_required_plan_nudge(
                scratch,
                _completion_for_names(tool_names, created_at),
                created_at=created_at,
            )
            guidance.append(scratch[0])
            plan_nudged = True
            continue

        correction_open = evidence_observations < task.max_corrections_per_attempt
        if evidence_missing and not tool_names and correction_open:
            guidance.append(
                _evidence_observation(
                    task, missing, open_plan_steps, created_at
                )
            )
            evidence_observations += 1
        elif evidence_missing and validator_failed and correction_open:
            guidance.append(
                _evidence_observation(
                    task, missing, open_plan_steps, created_at
                )
            )
            evidence_observations += 1
    if (
        state.pending
        and not state.plain_provisional
        and state.validator_rejection
        and not validator_instruction_appended
    ):
        scratch = []
        append_validator_correction_instruction(scratch, created_at=created_at)
        guidance.append(scratch[0])
        validator_instruction_appended = True
    if state.pending and not state.plain_provisional and not no_progress_observation_appended:
        scratch = []
        append_no_progress_observation(
            scratch,
            metadata={"consecutive_no_progress_batches": state.no_progress_count},
            created_at=created_at,
        )
        guidance.append(scratch[0])
        no_progress_observation_appended = True
    return tuple(guidance)


@dataclass(frozen=True)
class _BatchScan:
    tool_names: tuple[str, ...]
    validator_rejection: bool
    state_changed: bool
    fingerprints: tuple[str, ...]


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
    proposed tool names, the validator-rejection signal and the observation
    fingerprints used by the harness's no-progress progress replay."""
    batches: list[_BatchScan] = []
    attempt_events = [
        event
        for event in events
        if event.payload.get("attempt_number") == attempt_number
    ]
    index = 0
    while index < len(attempt_events):
        event = attempt_events[index]
        index += 1
        if event.event_type is not EventType.MODEL_RESPONSE_RECEIVED:
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
        fingerprints: list[str] = []
        while index < len(attempt_events) and attempt_events[index].event_type not in {
            EventType.MODEL_RESPONSE_RECEIVED,
            EventType.ATTEMPT_OUTCOME_RECORDED,
        }:
            following = attempt_events[index]
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
                fingerprint = _execution_fingerprint(following.payload, created_at)
                if fingerprint is not None:
                    fingerprints.append(fingerprint)
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
                fingerprints=tuple(fingerprints),
            )
        )
    return batches


def _execution_fingerprint(payload: dict[str, object], created_at: datetime) -> str | None:
    """observation_fingerprint over one durable tool execution, so the
    no-progress counter is replayed with the harness's own progress rule."""
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
    return observation_fingerprint(
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
    seen: set[str] = set()
    count = 0
    for batch in batches:
        batch_fingerprints = set(batch.fingerprints)
        if batch_fingerprints - seen or batch.state_changed:
            count = 0
        else:
            count += 1
        seen |= batch_fingerprints
    return count


def _terminal_synthesis_state(
    batches: list[_BatchScan],
    events: list[SessionEvent],
    attempt_number: int,
    *,
    task: HarnessTask,
    session: Session,
    created_at: datetime,
) -> _TerminalSynthesisState:
    no_progress_count = _no_progress_counter(batches)
    validator_rejection = bool(batches and batches[-1].validator_rejection)
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
    pending = plain_provisional or validator_rejection or no_progress_triggered
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
    from agent_core.harness.completion_blocking import current_task_plan

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


def _evidence_observation(
    task: HarnessTask,
    missing: tuple[str, ...],
    open_plan_steps: tuple[str, ...],
    created_at: datetime,
) -> SessionMessage:
    scratch: list[SessionMessage] = []
    append_missing_evidence_observation(
        scratch,
        missing=missing,
        open_plan_steps=open_plan_steps,
        definition=task.agent_definition,
        trusted_evidence_tools=task.trusted_evidence_tools,
        created_at=created_at,
    )
    return scratch[0]


def _nudge_triggered(tool_names: list[str] | tuple[str, ...]) -> bool:
    if "agent.plan" in tool_names:
        return False
    if tool_names and tool_names[0] == "agent.clarify":
        return False
    return True


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


def _completion_for_names(
    names: list[str] | tuple[str, ...],
    created_at: datetime,
) -> ModelCompletion:
    # Only the tool-call names are consumed (append_required_plan_nudge);
    # the assistant content is a non-blank placeholder so the message model
    # accepts the synthetic completion.
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="required-plan nudge rebuild",
            created_at=created_at,
        ),
        tool_calls=tuple(
            ToolCall(
                tool_call_id=ToolCallId(UUID(int=index + 1)),
                name=name,
                arguments={},
                created_at=created_at,
            )
            for index, name in enumerate(names)
        ),
    )


def _continuation_boundary_index(events: list[SessionEvent]) -> int | None:
    """Index of the last continuation snapshot boundary in the durable stream.

    CLARIFICATION_REQUESTED / APPROVAL_REQUESTED carry the conversation
    snapshot the recovered continuation replays from; every event at or
    before that index is already materialized in the recovered conversation
    and must not be mirrored again.
    """
    boundary_index: int | None = None
    for index, event in enumerate(events):
        if event.event_type in {
            EventType.CLARIFICATION_REQUESTED,
            EventType.APPROVAL_REQUESTED,
        }:
            boundary_index = index
    return boundary_index


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
    synthesis."""
    del full_stream
    state = _terminal_synthesis_state(
        _scan_attempt_batches(events, attempt_number, created_at),
        events,
        attempt_number,
        task=task,
        session=session,
        created_at=created_at,
    )
    return state.pending
