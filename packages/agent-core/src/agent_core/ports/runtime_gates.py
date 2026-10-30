"""Scoped gate use cases; infrastructure implements native observations."""

from collections.abc import Callable
from typing import Any, Protocol

from agent_core.domain.runtime_gates import GateCommand


class RuntimeGatePort(Protocol):
    def change(
        self, command: GateCommand, digest: str, recheck: Callable[[], None]
    ) -> dict[str, Any]: ...
    def read(self, operation: str | None = None) -> dict[str, Any]: ...
