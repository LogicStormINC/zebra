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

from datetime import datetime
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import ToolCallId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import Session
from agent_core.domain.tools import ToolCall
from agent_core.harness.attempt_result import (
    append_no_progress_observation,
    update_observation_progress,
)
from agent_core.harness.capability_guidance import append_required_plan_nudge
from agent_core.harness.completion_blocking import append_missing_evidence_observation
from agent_core.harness.completion_evidence import (
    evaluate_context_completion_evidence,
    persisted_completion_evidence_events,
)
from agent_core.harness.concurrent_batch import DEFAULT_REPEAT_HARD_STOP_THRESHOLD
from agent_core.harness.context_recovery import append_validator_correction_instruction
from agent_core.harness.models import HarnessAttempt, HarnessContext, HarnessEventDraft, HarnessTask

from zebra_agent_worker.terminal_synthesis import (
    _durable_plan,
    _scan_attempt_batches,
    _terminal_synthesis_state,
)


def rebuilt_runtime_guidance(
    events: list[SessionEvent],
    *,
    attempt: HarnessAttempt,
    task: HarnessTask,
    session: Session,
    completion_evidence_events: tuple[HarnessEventDraft, ...],
    created_at: datetime,
    prior_messages: tuple[SessionMessage, ...] = (),
    base_evidence_events: tuple[HarnessEventDraft, ...] = (),
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
        base_evidence_events=base_evidence_events,
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
    base_evidence_events: tuple[HarnessEventDraft, ...] = (),
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
        evidence_missing=evidence_missing,
    )

    progress_metadata: dict[str, object] = {}
    recoverable_deny_count = 0
    for batch in batches:
        tool_names = batch.tool_names
        validator_failed = batch.validator_rejection
        if batch.recoverable_deny:
            recoverable_deny_count += 1
        policy_recovery_triggered = recoverable_deny_count >= 2
        progress_metadata = update_observation_progress(
            progress_metadata,
            batch.observations,
            state_changed=batch.state_changed,
            threshold=DEFAULT_REPEAT_HARD_STOP_THRESHOLD,
        )
        batch_no_progress = progress_metadata.get("consecutive_no_progress_batches", 0)
        no_progress_triggered = (
            isinstance(batch_no_progress, int)
            and not isinstance(batch_no_progress, bool)
            and batch_no_progress >= DEFAULT_REPEAT_HARD_STOP_THRESHOLD
        )
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

        # Historical evidence state: the harness's evidence gate for this
        # batch ran when the durable stream contained only the events up to
        # this batch (a typed producer executed later must not erase an
        # observation that was already appended).
        batch_status = evaluate_context_completion_evidence(
            HarnessContext(
                task=task,
                session=session,
                attempt=HarnessAttempt(number=attempt_number, started_at=created_at),
                completion_evidence_events=(
                    *base_evidence_events,
                    *persisted_completion_evidence_events(events[: batch.end_index]),
                ),
            ),
            (),
        )
        batch_evidence_missing = not batch_status.satisfied
        correction_open = evidence_observations < task.max_corrections_per_attempt
        if batch_evidence_missing and not tool_names and correction_open:
            guidance.append(
                _evidence_observation(
                    task,
                    batch_status.missing,
                    batch_status.open_plan_steps,
                    created_at,
                )
            )
            evidence_observations += 1
        elif (
            batch_evidence_missing
            and (validator_failed or no_progress_triggered or policy_recovery_triggered)
            and correction_open
        ):
            guidance.append(
                _evidence_observation(
                    task,
                    batch_status.missing,
                    batch_status.open_plan_steps,
                    created_at,
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
