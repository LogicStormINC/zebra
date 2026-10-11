"""Idempotent Tool gateway cleanup with durable failure evidence."""

from datetime import datetime
from typing import Any

import zebra_agent_worker.runtime_authority as runtime_authority
from zebra_agent_worker.execution_recovery import persist_runtime_cleanup_failure


class GatewayRelease:
    def __init__(
        self, gateway: Any, recorder: Any, *, started_at: datetime, attempt_number: int = 1
    ) -> None:
        self._gateway = gateway
        self.recorder = recorder
        self._started_at = started_at
        self._attempt_number = attempt_number
        self._released = False

    def __call__(self) -> Exception | None:
        if self._released:
            return None
        self._released = True
        error = runtime_authority.close_tool_gateway(self._gateway)
        if error is not None:
            try:
                persist_runtime_cleanup_failure(
                    recorder=self.recorder,
                    error=error,
                    target="tool_gateway",
                    created_at=self._started_at,
                    attempt_number=self._attempt_number,
                )
            except Exception as evidence_error:
                error.add_note(f"cleanup evidence unavailable: {type(evidence_error).__name__}")
        return error
