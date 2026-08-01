from dataclasses import dataclass

from agent_core.domain.messages import SessionMessage
from agent_core.domain.model_media import ModelMediaInput
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.ports.model_gateway import ModelGatewayPort


@dataclass(frozen=True)
class ScriptedModelResponse:
    completion: ModelCompletion


class ScriptedModelGateway(ModelGatewayPort):
    def __init__(self, responses: tuple[ScriptedModelResponse, ...]) -> None:
        if not responses:
            raise ValueError("scripted model gateway requires at least one response")
        self._responses = responses
        self._cursor = 0
        self._requests: list[tuple[SessionMessage, ...]] = []
        self._tool_requests: list[tuple[ModelToolDefinition, ...]] = []

    @property
    def requests(self) -> tuple[tuple[SessionMessage, ...], ...]:
        return tuple(self._requests)

    @property
    def tool_requests(self) -> tuple[tuple[ModelToolDefinition, ...], ...]:
        return tuple(self._tool_requests)

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        media_inputs: tuple[ModelMediaInput, ...] = (),
    ) -> ModelCompletion:
        del media_inputs
        if self._cursor >= len(self._responses):
            raise RuntimeError("scripted model gateway has no remaining responses")
        self._requests.append(tuple(messages))
        self._tool_requests.append(tools)
        response = self._responses[self._cursor]
        self._cursor += 1
        return response.completion
