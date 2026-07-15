from agent_core.harness.models import (
    HarnessAttemptOutcome,
    HarnessAttemptResult,
    HarnessRunResult,
    HarnessStopReason,
    HarnessTask,
)


class HarnessStoppingPolicy:
    def build_run_result(
        self,
        task: HarnessTask,
        *,
        attempts_used: int,
        model_calls_used: int,
        tool_calls_used: int,
        attempt_result: HarnessAttemptResult,
    ) -> HarnessRunResult:
        can_retry = self.should_retry(
            max_attempts=task.max_attempts,
            max_model_calls=task.max_model_calls,
            max_tool_calls=task.max_tool_calls,
            attempts_used=attempts_used,
            model_calls_used=model_calls_used,
            tool_calls_used=tool_calls_used,
            attempt_result=attempt_result,
        )
        stop_reason = self._stop_reason_for(
            can_retry=can_retry,
            max_attempts=task.max_attempts,
            max_model_calls=task.max_model_calls,
            max_tool_calls=task.max_tool_calls,
            attempts_used=attempts_used,
            model_calls_used=model_calls_used,
            tool_calls_used=tool_calls_used,
            attempt_result=attempt_result,
        )
        return HarnessRunResult(
            final_outcome=attempt_result.outcome,
            stop_reason=stop_reason,
            attempts_used=attempts_used,
            max_attempts=task.max_attempts,
            model_calls_used=model_calls_used,
            max_model_calls=task.max_model_calls,
            tool_calls_used=tool_calls_used,
            max_tool_calls=task.max_tool_calls,
            can_retry=can_retry,
            summary=attempt_result.summary,
            last_attempt=attempt_result,
        )

    @staticmethod
    def should_retry(
        *,
        max_attempts: int,
        max_model_calls: int | None,
        max_tool_calls: int | None,
        attempts_used: int,
        model_calls_used: int,
        tool_calls_used: int,
        attempt_result: HarnessAttemptResult,
    ) -> bool:
        if attempt_result.outcome in {
            HarnessAttemptOutcome.WAITING_APPROVAL,
            HarnessAttemptOutcome.WAITING_INPUT,
        }:
            return False
        if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED:
            return False
        if max_model_calls is not None and model_calls_used >= max_model_calls:
            return False
        if max_tool_calls is not None and tool_calls_used >= max_tool_calls:
            return False
        return attempts_used < max_attempts

    @staticmethod
    def _stop_reason_for(
        *,
        can_retry: bool,
        max_attempts: int,
        max_model_calls: int | None,
        max_tool_calls: int | None,
        attempts_used: int,
        model_calls_used: int,
        tool_calls_used: int,
        attempt_result: HarnessAttemptResult,
    ) -> HarnessStopReason:
        if attempt_result.outcome is HarnessAttemptOutcome.WAITING_APPROVAL:
            return HarnessStopReason.APPROVAL_REQUIRED
        if attempt_result.outcome is HarnessAttemptOutcome.WAITING_INPUT:
            return HarnessStopReason.CLARIFICATION_REQUIRED
        if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED:
            return HarnessStopReason.COMPLETED
        if max_model_calls is not None and model_calls_used >= max_model_calls:
            return HarnessStopReason.MODEL_CALL_BUDGET_EXHAUSTED
        if max_tool_calls is not None and tool_calls_used >= max_tool_calls:
            return HarnessStopReason.TOOL_CALL_BUDGET_EXHAUSTED
        if can_retry:
            return HarnessStopReason.RETRY_ALLOWED
        if attempts_used >= max_attempts:
            return HarnessStopReason.RETRY_EXHAUSTED
        return HarnessStopReason.FAILED_TERMINAL
