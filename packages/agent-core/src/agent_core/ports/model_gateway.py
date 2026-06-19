from typing import Protocol

from agent_core.domain.messages import SessionMessage


class ModelGatewayPort(Protocol):
    def complete(self, messages: list[SessionMessage]) -> SessionMessage: ...
