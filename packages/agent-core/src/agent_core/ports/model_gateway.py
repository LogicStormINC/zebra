from collections.abc import Callable
from typing import Protocol, runtime_checkable

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelTextDelta,
    ModelToolDefinition,
)


@runtime_checkable
class ModelContextWindowPort(Protocol):
    @property
    def context_window(self) -> ModelContextWindow: ...


class ModelGatewayPort(Protocol):
    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion: ...


@runtime_checkable
class StreamingModelGatewayPort(Protocol):
    def complete_stream(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        on_text_delta: Callable[[ModelTextDelta], None],
    ) -> ModelCompletion: ...
