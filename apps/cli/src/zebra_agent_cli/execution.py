from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.harness.models import HarnessLoopResult
from agent_core.harness.projection import HarnessTraceProjector
from agent_integrations import build_model_gateway
from agent_runtime import run_local_harness
from agent_security import PolicyProfile
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_config import ZebraAgentSettings


@dataclass(frozen=True)
class DurableRunResult:
    harness_result: HarnessLoopResult
    workspace_root: Path
    policy_profile: str


def execute_durable_run(
    *,
    prompt: str,
    title: str,
    workspace_root: Path,
    database_path: Path,
    settings: ZebraAgentSettings,
    policy_profile: PolicyProfile = PolicyProfile.WORKSPACE_WRITE,
) -> DurableRunResult:
    result = run_local_harness(
        prompt=prompt,
        title=title,
        workspace_root=workspace_root,
        model_gateway=build_model_gateway(settings),
        policy_profile=policy_profile,
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
    trace = HarnessTraceProjector().project(harness_result)
    return {
        "executed": True,
        "status": harness_result.session.status.value,
        "attempts_used": harness_result.run_result.attempts_used,
        "stop_reason": harness_result.run_result.stop_reason.value,
        "assistant_message": harness_result.attempt_result.metadata.get("assistant_message"),
        "policy_profile": result.policy_profile,
        "workspace_root": str(result.workspace_root),
        "trace": [
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
            for attempt in trace.attempts
        ],
    }
