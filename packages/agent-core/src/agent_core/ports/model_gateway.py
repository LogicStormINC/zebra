from typing import Protocol

from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion


class ModelGatewayPort(Protocol):
    def complete(self, messages: list[SessionMessage]) -> ModelCompletion: ...
