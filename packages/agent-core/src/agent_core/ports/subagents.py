from typing import Protocol

from agent_core.domain.identifiers import SubagentId
from agent_core.domain.subagents import ResearchSubagentResult, ResearchSubagentTask


class SubagentPort(Protocol):
    def spawn(self, task: ResearchSubagentTask) -> SubagentId: ...

    def join(self, subagent_id: SubagentId) -> ResearchSubagentResult: ...

    def cancel(self, subagent_id: SubagentId) -> bool: ...

    def collect(self, subagent_id: SubagentId) -> ResearchSubagentResult | None: ...
