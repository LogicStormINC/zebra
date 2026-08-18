from agent_core.harness import HarnessContext, SingleAttemptOrchestrator
from agent_core.harness.completion_blocking import enforce_plan_completion_coherence
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.harness.reconstruction import ReconstructionMismatchError
from agent_core.ports.runtime import RuntimeHandle, RuntimePort, RuntimeSnapshot

from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.execution_errors import error_metadata, exception_attempt_result


def execute_attempt(
    orchestrator: SingleAttemptOrchestrator,
    context: HarnessContext,
    *,
    continuation: ApprovedContinuation | None,
    clarification: ClarificationContinuation | None,
    runtime: RuntimePort,
    runtime_handle: RuntimeHandle,
) -> tuple[HarnessAttemptResult, RuntimeSnapshot | None]:
    try:
        if continuation is not None:
            result = orchestrator.continue_approved_tool_call(
                context,
                initial_completion=continuation.completion,
                tool_call=continuation.tool_call,
                remaining_tool_calls=continuation.remaining_tool_calls,
                conversation=continuation.conversation,
                model_calls_used=continuation.model_calls_used,
                tool_calls_executed=continuation.tool_calls_executed,
            )
        elif clarification is not None:
            result = orchestrator.continue_clarification(
                context,
                tool_call=clarification.tool_call,
                response=clarification.response,
                conversation=clarification.conversation,
                model_calls_used=clarification.model_calls_used,
                tool_calls_executed=clarification.tool_calls_executed,
                assistant_message=clarification.assistant_message,
            )
        else:
            result = orchestrator.run(context)
    except Exception as exc:
        pre_dispatch = isinstance(exc, ReconstructionMismatchError | ContextWindowExceededError)
        result = exception_attempt_result(
            exc,
            error_metadata(
                exc,
                clarification,
                continuation,
                dispatch_attempted=not pre_dispatch,
            ),
        )
    result = enforce_plan_completion_coherence(context, result)
    if result.outcome is not HarnessAttemptOutcome.SUSPENDED:
        return result, None
    try:
        snapshot = runtime.snapshot(runtime_handle)
        if snapshot.snapshot_path is None:
            raise ValueError("runtime did not return snapshot_path")
    except Exception as exc:
        return (
            HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.FAILED,
                summary="runtime snapshot failed",
                metadata={
                    "stop_reason": "runtime_snapshot_failed",
                    "error_type": type(exc).__name__,
                    "model_calls_used": result.metadata.get("model_calls_used", 0),
                    "tool_calls_executed": result.metadata.get("tool_calls_executed", 0),
                },
            ),
            None,
        )
    return result, snapshot
