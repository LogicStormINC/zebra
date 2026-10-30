"""Exact original bytes and explicit one-shot termination; no retry policy."""

from collections.abc import Callable
from hashlib import sha256
from typing import Any

from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.domain.runtime_gate_termination import GateTerminationCommand
from agent_core.ports.runtime_gate_termination import RuntimeGateTerminationPort


class RuntimeGateTerminationService:
    def __init__(self, store: RuntimeGateTerminationPort) -> None:
        self.store = store

    def terminate(self, raw: bytes, recheck: Callable[[], None]) -> dict[str, Any]:
        if not raw or len(raw) > 65536:
            raise ValueError("INVALID_ARGUMENT")
        command = GateTerminationCommand.model_validate(load_bundle_json(raw))
        return self.store.terminate(command, sha256(raw).hexdigest(), recheck)

    def read(self, operation: str) -> dict[str, Any]:
        return self.store.read(operation)
