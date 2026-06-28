"""Tools package for Zebra Agent."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_tools.builtin.command import CommandRunTool, command_run_contract
    from agent_tools.builtin.files import FileReadTool, file_read_contract
    from agent_tools.builtin.git import GitStatusTool, git_status_contract
    from agent_tools.builtin.patch import PatchApplyTool, patch_apply_contract
    from agent_tools.builtin.tests import TestsRunTool, tests_run_contract
    from agent_tools.contracts import RegisteredTool, ToolContract
    from agent_tools.executor import ToolExecutor
    from agent_tools.mcp_proxy import (
        McpProxyRequest,
        McpProxyResponse,
        McpProxyTransport,
        McpToolTarget,
        build_mcp_proxy_request,
        parse_mcp_tool_name,
    )
    from agent_tools.registry import ToolRegistry

__all__ = [
    "CommandRunTool",
    "FileReadTool",
    "GitStatusTool",
    "McpProxyRequest",
    "McpProxyResponse",
    "McpProxyTransport",
    "McpToolTarget",
    "PatchApplyTool",
    "RegisteredTool",
    "TestsRunTool",
    "ToolContract",
    "ToolExecutor",
    "ToolRegistry",
    "build_mcp_proxy_request",
    "command_run_contract",
    "file_read_contract",
    "git_status_contract",
    "parse_mcp_tool_name",
    "patch_apply_contract",
    "tests_run_contract",
]

_EXPORTS = {
    "CommandRunTool": ("agent_tools.builtin.command", "CommandRunTool"),
    "FileReadTool": ("agent_tools.builtin.files", "FileReadTool"),
    "GitStatusTool": ("agent_tools.builtin.git", "GitStatusTool"),
    "McpProxyRequest": ("agent_tools.mcp_proxy", "McpProxyRequest"),
    "McpProxyResponse": ("agent_tools.mcp_proxy", "McpProxyResponse"),
    "McpProxyTransport": ("agent_tools.mcp_proxy", "McpProxyTransport"),
    "McpToolTarget": ("agent_tools.mcp_proxy", "McpToolTarget"),
    "PatchApplyTool": ("agent_tools.builtin.patch", "PatchApplyTool"),
    "RegisteredTool": ("agent_tools.contracts", "RegisteredTool"),
    "TestsRunTool": ("agent_tools.builtin.tests", "TestsRunTool"),
    "ToolContract": ("agent_tools.contracts", "ToolContract"),
    "ToolExecutor": ("agent_tools.executor", "ToolExecutor"),
    "ToolRegistry": ("agent_tools.registry", "ToolRegistry"),
    "build_mcp_proxy_request": ("agent_tools.mcp_proxy", "build_mcp_proxy_request"),
    "command_run_contract": ("agent_tools.builtin.command", "command_run_contract"),
    "file_read_contract": ("agent_tools.builtin.files", "file_read_contract"),
    "git_status_contract": ("agent_tools.builtin.git", "git_status_contract"),
    "parse_mcp_tool_name": ("agent_tools.mcp_proxy", "parse_mcp_tool_name"),
    "patch_apply_contract": ("agent_tools.builtin.patch", "patch_apply_contract"),
    "tests_run_contract": ("agent_tools.builtin.tests", "tests_run_contract"),
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
