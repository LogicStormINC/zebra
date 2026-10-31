from __future__ import annotations

from agent_core.domain.subagents import DelegationMode
from agent_tools import AuthorizedMcpToolCatalog, ClarifyTool, PlanTool, ToolExecutor, ToolRegistry


def build_readonly_gateway(cls, runtime, check):
    # ponytail: this explicit zero-workspace surface only reuses native plan/clarify.
    # Files/commands require the separate private runtime release, never this mode.
    self = cls.__new__(cls)
    self._runtime, self._runtime_handle, self._network_check = runtime, None, check
    self._output_projector, self._subagents = None, None
    self._delegation_mode = DelegationMode.DISABLED
    self._skill_component_names, self._skill_requirements = (), ()
    self._mcp_catalog = AuthorizedMcpToolCatalog(())
    self._runtime_free_mcp_tools = frozenset()
    registry = ToolRegistry()
    for tool in (ClarifyTool(), PlanTool()):
        registry.register(tool.contract, tool.handle)
    self._model_tools = registry.model_tools()
    self._parallel_safe_tools = registry.parallel_safe_names()
    self._parallel_batch_limits = {}
    self._runtime_free_web_tools = frozenset(tool.name for tool in self._model_tools)
    self._executor = ToolExecutor(registry)
    return self
