from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessLoop, HarnessTask, SingleAttemptOrchestrator
from agent_core.harness.task_contracts import infer_task_contract
from agent_observability import (
    EvalCase,
    LocalEvalRunner,
    LocalReleaseGate,
    ReplayResult,
    load_eval_cases,
)


def main() -> int:
    cases = load_eval_cases(Path("evals/cases"))
    executed = tuple(_execute_replay(case) for case in cases)
    replays = tuple(item[0] for item in executed)
    run_result = LocalEvalRunner().run(cases, replays)
    gate_result = LocalReleaseGate().evaluate(run_result)
    print(
        "eval release gate: "
        f"passed={gate_result.passed} "
        f"pass_rate={gate_result.pass_rate:.2f} "
        f"average_score={gate_result.average_score:.2f} "
        f"cases={run_result.total_count}"
    )
    for reason in gate_result.reasons:
        print(f"- {reason}")
    report_path = Path("evals/reports/deterministic-harness.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "gate": {
                    "average_score": gate_result.average_score,
                    "pass_rate": gate_result.pass_rate,
                    "passed": gate_result.passed,
                },
                "kind": "deterministic_harness_trace",
                "runs": [item[1] for item in executed],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"deterministic trace artifact: {report_path}")
    return 0 if gate_result.passed else 1


def _execute_replay(case: EvalCase) -> tuple[ReplayResult, dict[str, object]]:
    """Run the real deterministic Harness; never synthesize metrics from thresholds."""

    created_at = datetime(2026, 9, 20, tzinfo=UTC)
    tool_calls = tuple(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="eval.observe",
            arguments={"case_id": case.case_id, "step": index + 1},
            created_at=created_at,
            provider_call_id=f"{case.case_id}-tool-{index + 1}",
        )
        for index in range(max(1, case.min_tool_results))
    )
    source_url = f"https://eval.zebra.local/{case.case_id}"
    responses = tuple(
        ScriptedModelResponse(
            completion=_completion(
                f"Collect deterministic evidence step {index + 1}.",
                created_at=created_at,
                tool_call=tool_call,
            )
        )
        for index, tool_call in enumerate(tool_calls)
    ) + (
        ScriptedModelResponse(
            completion=_completion(
                (
                    "# Outcome\n\n- The requested deterministic scenario completed and its "
                    "required result was checked.\n\n"
                    + "The trace records the task contract, tool observation, terminal outcome, "
                    "delivery assessment, and any durable artifact reference. "
                    * 3
                    + f"\n\nEvidence: {source_url}"
                ),
                created_at=created_at,
            )
        ),
    )
    inferred = infer_task_contract(case.prompt)
    contract = replace(
        inferred,
        require_evidence_reference=(inferred.require_evidence_reference or case.require_evidence),
        require_matching_citation=(inferred.require_matching_citation or case.require_evidence),
        require_artifact=case.require_artifact,
    )
    run = HarnessLoop().run(
        HarnessTask(
            title=case.title,
            user_input=case.prompt,
            max_model_calls=len(responses),
            max_tool_calls=len(tool_calls),
            acceptance_contract=contract,
        ),
        SingleAttemptOrchestrator(
            ScriptedModelGateway(responses=responses),
            _AllowAllPolicy(),
            _EvalToolGateway(case),
            synthesize_tool_results=True,
        ).run,
        created_at=created_at,
    )
    tool_results = sum(
        event.event_type in {EventType.TOOL_EXECUTION_COMPLETED, EventType.TOOL_EXECUTION_FAILED}
        for event in run.events
    )
    replay = ReplayResult(
        session_id=str(run.session.session_id),
        event_count=len(run.events),
        tool_result_count=tool_results,
        audit_steps=len(run.events),
        model_calls=run.run_result.model_calls_used,
        total_tokens=sum(
            int(event.payload.get("total_tokens") or 0)
            for event in run.events
            if event.event_type is EventType.MODEL_RESPONSE_RECEIVED
        ),
        cost_usd=0.0,
        terminal_outcome=run.attempt_result.outcome.value,
        stop_reason=run.run_result.stop_reason.value,
        delivery_status=_delivery_value(run, "status"),
        evidence_count=len(_delivery_values(run, "evidence_refs")),
        artifact_count=len(_delivery_values(run, "artifact_refs")),
        failed_tool_results=sum(
            event.event_type is EventType.TOOL_EXECUTION_FAILED for event in run.events
        ),
    )
    return replay, {
        "case_id": case.case_id,
        "events": [
            {
                "event_type": event.event_type.value,
                "payload": event.payload,
                "sequence": event.sequence,
            }
            for event in run.events
        ],
        "replay": replay.__dict__,
        "terminal": {
            "delivery_assessment": run.attempt_result.metadata.get("delivery_assessment"),
            "outcome": run.attempt_result.outcome.value,
            "stop_reason": run.run_result.stop_reason.value,
        },
    }


class _AllowAllPolicy:
    def evaluate_tool_call(self, _tool_call: ToolCall) -> PolicyDecision:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason="deterministic eval tool is allowed",
            policy_profile="eval",
        )


class _EvalToolGateway:
    def __init__(self, case: EvalCase) -> None:
        self._case = case

    def execute(self, tool_call: ToolCall) -> ToolResult:
        metadata: dict[str, object] = {
            "postcondition_met": True,
            "source_url": f"https://eval.zebra.local/{self._case.case_id}",
        }
        if self._case.require_artifact:
            metadata["artifact_uri"] = f"artifact://eval/{self._case.case_id}/deliverable"
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=(
                f"evidence:{tool_call.arguments['step']} "
                f"https://eval.zebra.local/{self._case.case_id}"
            ),
            metadata=metadata,
        )


def _delivery_value(run: object, key: str) -> str | None:
    metadata = getattr(getattr(run, "attempt_result", None), "metadata", {})
    delivery = metadata.get("delivery_assessment") if isinstance(metadata, dict) else None
    value = delivery.get(key) if isinstance(delivery, dict) else None
    return value if isinstance(value, str) else None


def _delivery_values(run: object, key: str) -> tuple[str, ...]:
    metadata = getattr(getattr(run, "attempt_result", None), "metadata", {})
    delivery = metadata.get("delivery_assessment") if isinstance(metadata, dict) else None
    value = delivery.get(key) if isinstance(delivery, dict) else None
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _completion(
    content: str,
    *,
    created_at: datetime,
    tool_call: ToolCall | None = None,
) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=created_at,
        ),
        tool_calls=(tool_call,) if tool_call is not None else (),
    )


if __name__ == "__main__":
    raise SystemExit(main())
