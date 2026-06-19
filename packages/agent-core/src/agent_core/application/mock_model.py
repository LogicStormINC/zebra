from dataclasses import dataclass

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
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

    @property
    def requests(self) -> tuple[tuple[SessionMessage, ...], ...]:
        return tuple(self._requests)

    def complete(self, messages: list[SessionMessage]) -> ModelCompletion:
        if self._cursor >= len(self._responses):
            raise RuntimeError("scripted model gateway has no remaining responses")
        self._requests.append(tuple(messages))
        response = self._responses[self._cursor]
        self._cursor += 1
        return response.completion
