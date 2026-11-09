"""No retries or execution authority; retain caller's original operation identity."""

from collections.abc import Callable
from hashlib import sha256
from typing import Any

from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.domain.runtime_gates import GateCommand
from agent_core.ports.runtime_gates import RuntimeGatePort


class RuntimeGateService:
    def __init__(self, store: RuntimeGatePort) -> None:
        self.store = store

    def submit(self, raw: bytes, recheck: Callable[[], None]) -> dict[str, Any]:
        if not raw or len(raw) > 16384:
            raise ValueError("INVALID_ARGUMENT")
        command = GateCommand.model_validate(load_bundle_json(raw))
        return self.store.change(command, sha256(raw).hexdigest(), recheck)

    def observe(self, operation: str | None = None) -> dict[str, Any]:
        return self.store.read(operation)
