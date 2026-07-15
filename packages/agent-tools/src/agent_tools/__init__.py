"""Tools package for Zebra Agent."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_tools.builtin.clarify import ClarifyTool, clarify_contract
    from agent_tools.builtin.command import CommandRunTool, command_run_contract
    from agent_tools.builtin.files import FileReadTool, file_read_contract
    from agent_tools.builtin.git import GitStatusTool, git_status_contract
    from agent_tools.builtin.patch import PatchApplyTool, patch_apply_contract
    from agent_tools.builtin.plan import PlanTool, plan_contract
    from agent_tools.builtin.search import WorkspaceSearchTool, files_search_contract
    from agent_tools.builtin.tests import TestsRunTool, tests_run_contract
    from agent_tools.contracts import RegisteredTool, ToolContract
    from agent_tools.executor import ToolExecutor
    from agent_tools.mcp_gateway import McpProxyToolGateway
    from agent_tools.mcp_proxy import (
        McpProxyRequest,
        McpProxyResponse,
        McpProxyTransport,
        McpToolTarget,
        build_mcp_proxy_request,
        parse_mcp_tool_name,
    )
    from agent_tools.registry import ToolRegistry
    from agent_tools.skills import (
        SkillsListTool,
        SkillsReadTool,
        skills_list_contract,
        skills_read_contract,
    )
    from agent_tools.web_gateway import (
        WebFetchTool,
        WebGatewayError,
        WebGatewayRequest,
        WebGatewayResponse,
        WebGatewayTransport,
        web_fetch_contract,
    )
    from agent_tools.web_search import (
        WebSearchRequest,
        WebSearchResponse,
        WebSearchResult,
        WebSearchTool,
        WebSearchTransport,
        web_search_contract,
    )

__all__ = [
    "CommandRunTool",
    "ClarifyTool",
    "FileReadTool",
    "GitStatusTool",
    "McpProxyRequest",
    "McpProxyResponse",
    "McpProxyTransport",
    "McpProxyToolGateway",
    "McpToolTarget",
    "PatchApplyTool",
    "PlanTool",
    "RegisteredTool",
    "SkillsListTool",
    "SkillsReadTool",
    "TestsRunTool",
    "ToolContract",
    "ToolExecutor",
    "ToolRegistry",
    "WebFetchTool",
    "WorkspaceSearchTool",
    "WebGatewayError",
    "WebGatewayRequest",
    "WebGatewayResponse",
    "WebGatewayTransport",
    "WebSearchRequest",
    "WebSearchResponse",
    "WebSearchResult",
    "WebSearchTool",
    "WebSearchTransport",
    "build_mcp_proxy_request",
    "command_run_contract",
    "clarify_contract",
    "file_read_contract",
    "files_search_contract",
    "git_status_contract",
    "parse_mcp_tool_name",
    "patch_apply_contract",
    "plan_contract",
    "skills_list_contract",
    "skills_read_contract",
    "tests_run_contract",
    "web_fetch_contract",
    "web_search_contract",
]

_EXPORTS = {
    "ClarifyTool": ("agent_tools.builtin.clarify", "ClarifyTool"),
    "CommandRunTool": ("agent_tools.builtin.command", "CommandRunTool"),
    "FileReadTool": ("agent_tools.builtin.files", "FileReadTool"),
    "WorkspaceSearchTool": ("agent_tools.builtin.search", "WorkspaceSearchTool"),
    "GitStatusTool": ("agent_tools.builtin.git", "GitStatusTool"),
    "McpProxyRequest": ("agent_tools.mcp_proxy", "McpProxyRequest"),
    "McpProxyResponse": ("agent_tools.mcp_proxy", "McpProxyResponse"),
    "McpProxyTransport": ("agent_tools.mcp_proxy", "McpProxyTransport"),
    "McpProxyToolGateway": ("agent_tools.mcp_gateway", "McpProxyToolGateway"),
    "McpToolTarget": ("agent_tools.mcp_proxy", "McpToolTarget"),
    "PatchApplyTool": ("agent_tools.builtin.patch", "PatchApplyTool"),
    "PlanTool": ("agent_tools.builtin.plan", "PlanTool"),
    "SkillsListTool": ("agent_tools.skills", "SkillsListTool"),
    "SkillsReadTool": ("agent_tools.skills", "SkillsReadTool"),
    "RegisteredTool": ("agent_tools.contracts", "RegisteredTool"),
    "TestsRunTool": ("agent_tools.builtin.tests", "TestsRunTool"),
    "ToolContract": ("agent_tools.contracts", "ToolContract"),
    "ToolExecutor": ("agent_tools.executor", "ToolExecutor"),
    "ToolRegistry": ("agent_tools.registry", "ToolRegistry"),
    "WebFetchTool": ("agent_tools.web_gateway", "WebFetchTool"),
    "WebGatewayError": ("agent_tools.web_gateway", "WebGatewayError"),
    "WebGatewayRequest": ("agent_tools.web_gateway", "WebGatewayRequest"),
    "WebGatewayResponse": ("agent_tools.web_gateway", "WebGatewayResponse"),
    "WebGatewayTransport": ("agent_tools.web_gateway", "WebGatewayTransport"),
    "WebSearchRequest": ("agent_tools.web_search", "WebSearchRequest"),
    "WebSearchResponse": ("agent_tools.web_search", "WebSearchResponse"),
    "WebSearchResult": ("agent_tools.web_search", "WebSearchResult"),
    "WebSearchTool": ("agent_tools.web_search", "WebSearchTool"),
    "WebSearchTransport": ("agent_tools.web_search", "WebSearchTransport"),
    "build_mcp_proxy_request": ("agent_tools.mcp_proxy", "build_mcp_proxy_request"),
    "command_run_contract": ("agent_tools.builtin.command", "command_run_contract"),
    "clarify_contract": ("agent_tools.builtin.clarify", "clarify_contract"),
    "file_read_contract": ("agent_tools.builtin.files", "file_read_contract"),
    "files_search_contract": ("agent_tools.builtin.search", "files_search_contract"),
    "git_status_contract": ("agent_tools.builtin.git", "git_status_contract"),
    "parse_mcp_tool_name": ("agent_tools.mcp_proxy", "parse_mcp_tool_name"),
    "patch_apply_contract": ("agent_tools.builtin.patch", "patch_apply_contract"),
    "plan_contract": ("agent_tools.builtin.plan", "plan_contract"),
    "skills_list_contract": ("agent_tools.skills", "skills_list_contract"),
    "skills_read_contract": ("agent_tools.skills", "skills_read_contract"),
    "tests_run_contract": ("agent_tools.builtin.tests", "tests_run_contract"),
    "web_fetch_contract": ("agent_tools.web_gateway", "web_fetch_contract"),
    "web_search_contract": ("agent_tools.web_search", "web_search_contract"),
}


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module 'agent_tools' has no attribute {name!r}") from exc
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
