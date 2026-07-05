from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_core.domain.events import SessionEvent
from agent_core.harness.models import HarnessAttemptTrace, HarnessLoopResult
from agent_core.harness.projection import HarnessTraceProjector
from agent_integrations import build_model_gateway
from agent_runtime import run_local_harness
from agent_security import PolicyProfile
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    list_confirmed_repo_memories,
)
from zebra_agent_config import ZebraAgentSettings


@dataclass(frozen=True)
class DurableRunResult:
    harness_result: HarnessLoopResult
    workspace_root: Path
    policy_profile: str


@dataclass
class _PendingAttemptTrace:
    attempt_number: int
    assistant_message: str | None = None
    tools: list[dict[str, object]] = field(default_factory=list)
    pending_tool_name: str | None = None
    pending_tool_arguments: dict[str, object] = field(default_factory=dict)
    pending_policy_decision: str | None = None


def execute_durable_run(
    *,
    prompt: str,
    title: str,
    workspace_root: Path,
    database_path: Path,
    settings: ZebraAgentSettings,
    policy_profile: PolicyProfile = PolicyProfile.WORKSPACE_WRITE,
) -> DurableRunResult:
    confirmed_memories = list_confirmed_repo_memories(
        database_path,
        repo_id=str(workspace_root.resolve()),
    )
    result = run_local_harness(
        prompt=prompt,
        title=title,
        workspace_root=workspace_root,
        model_gateway=build_model_gateway(settings),
        policy_profile=policy_profile,
        confirmed_memories=confirmed_memories,
    )
    event_store = SQLiteEventStore(database_path)
    for event in result.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(result.session)
    return DurableRunResult(
        harness_result=result,
        workspace_root=workspace_root,
        policy_profile=policy_profile.value,
    )


def serialize_run_execution(result: DurableRunResult) -> dict[str, object]:
    harness_result = result.harness_result
    return {
        "executed": True,
        "status": harness_result.session.status.value,
        "attempts_used": harness_result.run_result.attempts_used,
        "stop_reason": harness_result.run_result.stop_reason.value,
        "assistant_message": harness_result.attempt_result.metadata.get("assistant_message"),
        "policy_profile": result.policy_profile,
        "workspace_root": str(result.workspace_root),
        "trace": _serialize_trace(HarnessTraceProjector().project(harness_result).attempts),
    }


def serialize_trace_events(events: tuple[SessionEvent, ...]) -> list[dict[str, object]]:
    attempts: dict[int, _PendingAttemptTrace] = {}
    for event in events:
        raw_attempt_number = event.payload.get("attempt_number")
        if not isinstance(raw_attempt_number, int) or raw_attempt_number <= 0:
            continue
        attempt = attempts.setdefault(
            raw_attempt_number,
            _PendingAttemptTrace(attempt_number=raw_attempt_number),
        )
        if event.event_type.value == "model_response_received":
            assistant_message = event.payload.get("assistant_message")
            if isinstance(assistant_message, str):
                attempt.assistant_message = assistant_message
        elif event.event_type.value == "tool_call_proposed":
            tool_name = event.payload.get("tool_name")
            arguments = event.payload.get("arguments")
            if isinstance(tool_name, str):
                attempt.pending_tool_name = tool_name
            if isinstance(arguments, dict):
                attempt.pending_tool_arguments = {
                    str(key): value for key, value in arguments.items()
                }
        elif event.event_type.value == "policy_decision_made":
            decision = event.payload.get("decision")
            if isinstance(decision, str):
                attempt.pending_policy_decision = decision
        elif event.event_type.value in {"tool_execution_completed", "tool_execution_failed"}:
            tool_name = event.payload.get("tool_name")
            status = event.payload.get("status")
            if not isinstance(tool_name, str) or not isinstance(status, str):
                continue
            output = event.payload.get("output")
            metadata = event.payload.get("metadata")
            attempt.tools.append(
                {
                    "tool_name": tool_name,
                    "status": status,
                    "arguments": (
                        dict(attempt.pending_tool_arguments)
                        if tool_name == attempt.pending_tool_name
                        else {}
                    ),
                    "output": output if isinstance(output, str) else "",
                    "metadata": dict(metadata) if isinstance(metadata, dict) else {},
                    "policy_decision": attempt.pending_policy_decision,
                }
            )
            attempt.pending_tool_name = None
            attempt.pending_tool_arguments = {}
            attempt.pending_policy_decision = None
    serialized: list[dict[str, object]] = []
    for _, attempt in sorted(attempts.items(), key=lambda item: item[0]):
        serialized.append(
            {
                "attempt_number": attempt.attempt_number,
                "assistant_message": attempt.assistant_message,
                "tools": attempt.tools,
            }
        )
    return serialized


def _serialize_trace(attempts: tuple[HarnessAttemptTrace, ...]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for attempt in attempts:
        serialized.append(
            {
                "attempt_number": attempt.attempt_number,
                "assistant_message": attempt.assistant_message,
                "tools": [
                    {
                        "tool_name": tool.tool_name,
                        "status": tool.status,
                        "arguments": tool.arguments,
                        "output": tool.output,
                        "metadata": tool.metadata,
                        "policy_decision": tool.policy_decision,
                    }
                    for tool in attempt.tools
                ],
            }
        )
    return serialized
