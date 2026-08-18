from typing import Protocol

from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationRequest,
)


class ContextMaterializationPort(Protocol):
    """Read-only composition boundary for the current Context input."""

    def materialize(self, request: ContextMaterializationRequest) -> ContextMaterialization: ...
