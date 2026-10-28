"""Storage authority for original gate commit exclusion."""

from collections.abc import Callable
from typing import Any, Protocol

from agent_core.domain.runtime_gate_termination import GateTerminationCommand


class RuntimeGateTerminationPort(Protocol):
    def terminate(
        self, command: GateTerminationCommand, digest: str, recheck: Callable[[], None]
    ) -> dict[str, Any]: ...
    def read(self, operation: str) -> dict[str, Any]: ...
