"""Generic Task attempt policy (Wave 5 Phase 1).

The policy is frozen at Task creation and must never be expanded by a
continuation or client. v1 caps: max 2 attempts, max 1 evidence correction
per attempt. Coverage/correction execution is Phase 2; the caps and the
retryable machine-code allowlist are frozen here so recovery can fail closed
on any drift.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_ATTEMPTS_CAP = 2
MAX_CORRECTIONS_PER_ATTEMPT_CAP = 1
DEFAULT_RETRYABLE_STOP_REASONS = ("model_execution_failed",)


@dataclass(frozen=True)
class TaskAttemptPolicy:
    max_attempts: int = 1
    max_corrections_per_attempt: int = 0
    execution_profile_id: str | None = None
    retryable_stop_reasons: tuple[str, ...] = DEFAULT_RETRYABLE_STOP_REASONS

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool):
            raise ValueError("max_attempts must be an integer")
        if not 1 <= self.max_attempts <= MAX_ATTEMPTS_CAP:
            raise ValueError(f"max_attempts must be within 1..{MAX_ATTEMPTS_CAP} (v1 cap)")
        if not isinstance(self.max_corrections_per_attempt, int) or isinstance(
            self.max_corrections_per_attempt, bool
        ):
            raise ValueError("max_corrections_per_attempt must be an integer")
        if not 0 <= self.max_corrections_per_attempt <= MAX_CORRECTIONS_PER_ATTEMPT_CAP:
            raise ValueError(
                "max_corrections_per_attempt must be within "
                f"0..{MAX_CORRECTIONS_PER_ATTEMPT_CAP} (v1 cap)"
            )
        if self.execution_profile_id is not None:
            normalized = self.execution_profile_id.strip()
            if not normalized:
                raise ValueError("execution_profile_id must not be blank")
            object.__setattr__(self, "execution_profile_id", normalized)
        normalized_reasons: list[str] = []
        for reason in self.retryable_stop_reasons:
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("retryable_stop_reasons must be non-blank machine codes")
            if reason.strip() not in normalized_reasons:
                normalized_reasons.append(reason.strip())
        object.__setattr__(self, "retryable_stop_reasons", tuple(normalized_reasons))
