from typing import Protocol

from agent_core.domain.policies import PolicyDecision
from agent_core.domain.tools import ToolCall


class PolicyEnginePort(Protocol):
    def evaluate_tool_call(self, tool_call: ToolCall) -> PolicyDecision: ...
