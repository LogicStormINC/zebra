from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.sessions import Session
from agent_core.harness.models import (
    HarnessAttempt,
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessContext,
    HarnessLoopResult,
    HarnessTask,
)
from agent_core.harness.recorder import HarnessEventRecorder
from agent_core.harness.stopping import HarnessStoppingPolicy
from agent_core.harness.timing import SystemClock
from agent_core.ports.clock import ClockPort
from agent_core.ports.context_compiler import RuntimeEvidenceInput

AttemptRunner = Callable[[HarnessContext], HarnessAttemptResult]


class HarnessLoop:
    def __init__(
        self,
        *,
        stopping_policy: HarnessStoppingPolicy | None = None,
        clock: ClockPort | None = None,
    ) -> None:
        self._stopping_policy = stopping_policy or HarnessStoppingPolicy()
        self._clock = clock or SystemClock()

    def run(
        self,
        task: HarnessTask,
        attempt_runner: AttemptRunner,
        *,
        created_at: datetime | None = None,
        session_id: SessionId | None = None,
    ) -> HarnessLoopResult:
        started_at = created_at or self._clock.now()
        session = Session.create(title=task.title, created_at=started_at, session_id=session_id)
        recorder = HarnessEventRecorder(session=session, clock=self._clock)

        recorder.record(
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": task.title},
            created_at=started_at,
        )
        recorder.record(
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": task.user_input},
        )
        recorder.record(
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": task.title,
                "user_input": task.user_input,
                "workspace_root": (
                    str(task.workspace_root) if task.workspace_root is not None else None
                ),
                "policy_profile": task.policy_profile,
                "tool_profile": task.tool_profile.value,
                "network_profile": task.network_profile,
                "network_allowlist": list(task.network_allowlist),
                "mcp_allowlist": list(task.mcp_allowlist),
                "skill_components": list(task.skill_components),
                "max_attempts": task.max_attempts,
                "max_model_calls": task.max_model_calls,
                "max_tool_calls": task.max_tool_calls,
            },
        )
        attempt_results: list[HarnessAttemptResult] = []
        model_calls_used = 0
        tool_calls_used = 0
        runtime_evidence: list[RuntimeEvidenceInput] = []

        for attempt_number in range(1, task.max_attempts + 1):
            attempt_started_at = self._clock.now()
            attempt = HarnessAttempt(number=attempt_number, started_at=attempt_started_at)
            attempt_task = replace(task, runtime_evidence=tuple(runtime_evidence))
            recorder.record(
                event_type=EventType.HARNESS_ATTEMPT_STARTED,
                actor=EventActor.HARNESS,
                payload={"attempt_number": attempt.number},
                created_at=attempt_started_at,
            )

            attempt_result = attempt_runner(
                HarnessContext(task=attempt_task, session=recorder.session, attempt=attempt)
            )
            attempt_results.append(attempt_result)
            model_calls_used += int(attempt_result.metadata.get("model_calls_used", 1))
            tool_calls_used += int(attempt_result.metadata.get("tool_calls_executed", 0))
            runtime_evidence.extend(_runtime_evidence_from_attempt_result(attempt_result))
            for draft in attempt_result.emitted_events:
                recorder.record_draft(draft)

            run_result = self._stopping_policy.build_run_result(
                task,
                attempts_used=attempt.number,
                model_calls_used=model_calls_used,
                tool_calls_used=tool_calls_used,
                attempt_result=attempt_result,
            )
            if run_result.can_retry:
                continue

            if attempt_result.outcome in {
                HarnessAttemptOutcome.WAITING_APPROVAL,
                HarnessAttemptOutcome.WAITING_INPUT,
            }:
                return HarnessLoopResult(
                    session=recorder.session,
                    events=tuple(recorder.events),
                    attempt_result=attempt_result,
                    attempt_results=tuple(attempt_results),
                    run_result=run_result,
                )

            terminal_event_type = (
                EventType.SESSION_COMPLETED
                if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
                else EventType.SESSION_SUSPENDED
                if attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
                else EventType.SESSION_FAILED
            )
            payload = {
                "attempt_number": attempt.number,
                "summary": attempt_result.summary,
                "metadata": attempt_result.metadata,
            }
            recorder.record(
                event_type=terminal_event_type,
                actor=EventActor.HARNESS,
                payload=(
                    {
                        "reason": str(attempt_result.metadata.get("stop_reason", "budget")),
                        "metadata": attempt_result.metadata,
                    }
                    if terminal_event_type is EventType.SESSION_SUSPENDED
                    else payload
                ),
            )
            return HarnessLoopResult(
                session=recorder.session,
                events=tuple(recorder.events),
                attempt_result=attempt_result,
                attempt_results=tuple(attempt_results),
                run_result=run_result,
            )

        raise RuntimeError("harness loop exited without producing a terminal run result")


def _runtime_evidence_from_attempt_result(
    attempt_result: HarnessAttemptResult,
) -> tuple[RuntimeEvidenceInput, ...]:
    evidence: list[RuntimeEvidenceInput] = [
        RuntimeEvidenceInput(
            kind="conversation_summary",
            summary=attempt_result.summary,
        )
    ]
    plan_summary = _optional_string(attempt_result.metadata.get("plan_summary"))
    if plan_summary is not None:
        evidence.append(
            RuntimeEvidenceInput(
                kind="planner_summary",
                summary=plan_summary,
                metadata=_dict_metadata(attempt_result.metadata.get("plan_metadata")),
            )
        )
    verification_summary = _optional_string(attempt_result.metadata.get("verification_summary"))
    if verification_summary is not None:
        evidence.append(
            RuntimeEvidenceInput(
                kind="verifier_summary",
                summary=verification_summary,
                metadata={
                    "passed": bool(attempt_result.metadata.get("verification_passed")),
                    **_dict_metadata(attempt_result.metadata.get("verification_metadata")),
                },
            )
        )
    tool_status = _optional_string(attempt_result.metadata.get("tool_status"))
    if tool_status is not None:
        evidence.append(
            RuntimeEvidenceInput(
                kind="tool_status",
                summary=tool_status,
            )
        )
    tool_output = _optional_string(attempt_result.metadata.get("tool_output"))
    tool_name = _optional_string(attempt_result.metadata.get("tool_name"))
    if tool_output is not None and tool_name is not None:
        artifact_uri = _artifact_uri_from_metadata(attempt_result.metadata.get("tool_metadata"))
        evidence.append(
            RuntimeEvidenceInput(
                kind="tool_output_summary",
                summary=f"{tool_name}: {tool_output}",
                artifact_uri=artifact_uri,
            )
        )
    return tuple(evidence)


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _artifact_uri_from_metadata(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    artifact_uri = value.get("artifact_uri")
    if not isinstance(artifact_uri, str):
        return None
    stripped = artifact_uri.strip()
    return stripped or None


def _dict_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}
