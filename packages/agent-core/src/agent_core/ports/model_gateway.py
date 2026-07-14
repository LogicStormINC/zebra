from typing import Protocol

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition


class ModelGatewayPort(Protocol):
    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion: ...
