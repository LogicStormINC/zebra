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
        attempt_result: HarnessAttemptResult,
    ) -> HarnessRunResult:
        can_retry = self.should_retry(
            max_attempts=task.max_attempts,
            attempts_used=attempts_used,
            attempt_result=attempt_result,
        )
        stop_reason = self._stop_reason_for(
            can_retry=can_retry,
            max_attempts=task.max_attempts,
            attempts_used=attempts_used,
            attempt_result=attempt_result,
        )
        return HarnessRunResult(
            final_outcome=attempt_result.outcome,
            stop_reason=stop_reason,
            attempts_used=attempts_used,
            max_attempts=task.max_attempts,
            can_retry=can_retry,
            summary=attempt_result.summary,
            last_attempt=attempt_result,
        )

    @staticmethod
    def should_retry(
        *,
        max_attempts: int,
        attempts_used: int,
        attempt_result: HarnessAttemptResult,
    ) -> bool:
        if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED:
            return False
        return attempts_used < max_attempts

    @staticmethod
    def _stop_reason_for(
        *,
        can_retry: bool,
        max_attempts: int,
        attempts_used: int,
        attempt_result: HarnessAttemptResult,
    ) -> HarnessStopReason:
        if attempt_result.outcome is HarnessAttemptOutcome.COMPLETED:
            return HarnessStopReason.COMPLETED
        if can_retry:
            return HarnessStopReason.RETRY_ALLOWED
        if attempts_used >= max_attempts:
            return HarnessStopReason.RETRY_EXHAUSTED
        return HarnessStopReason.FAILED_TERMINAL
