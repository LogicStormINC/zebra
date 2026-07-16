"""Runtime package for Zebra Agent."""

from agent_core.ports.runtime import (
    RuntimeCapabilityError,
    RuntimeHandle,
    RuntimeSnapshot,
)

from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.git_commit import (
    WorkspaceCommitCommand,
    WorkspaceCommitError,
    WorkspaceCommitResult,
    WorkspaceCommitService,
)
from agent_runtime.git_diff import WorkspaceDiffError, WorkspaceDiffResult, WorkspaceDiffService
from agent_runtime.harness import LocalToolGateway, run_local_harness
from agent_runtime.mcp_inventory import (
    McpCapabilityInventory,
    McpServerCapability,
    McpToolCapability,
    build_mcp_capability_inventory,
)
from agent_runtime.mcp_protocol import McpProtocolError, McpServerSpec
from agent_runtime.mcp_stdio import LocalStdioMcpTransport
from agent_runtime.research import (
    LocalResearchSubagentRunner,
    ReadOnlyToolGateway,
    ResearchSubagentTool,
)
from agent_runtime.subagents import (
    LocalResearchSubagentCoordinator,
    SubagentLimitError,
    UnknownSubagentError,
)
from agent_runtime.workspace import (
    LocalWorkspace,
    LocalWorktree,
    WorkspaceError,
    WorkspaceLayout,
    WorkspacePathError,
)

__all__ = [
    "LocalRuntime",
    "LocalResearchSubagentCoordinator",
    "LocalResearchSubagentRunner",
    "LocalToolGateway",
    "LocalStdioMcpTransport",
    "LocalWorkspace",
    "LocalWorktree",
    "McpCapabilityInventory",
    "McpServerCapability",
    "McpToolCapability",
    "ReadOnlyToolGateway",
    "ResearchSubagentTool",
    "RuntimeCapabilityError",
    "RuntimeHandle",
    "RuntimeSnapshot",
    "McpProtocolError",
    "McpServerSpec",
    "SubagentLimitError",
    "UnknownSubagentError",
    "WorkspaceCommitCommand",
    "WorkspaceCommitError",
    "WorkspaceCommitResult",
    "WorkspaceCommitService",
    "WorkspaceDiffError",
    "WorkspaceDiffResult",
    "WorkspaceDiffService",
    "WorkspaceError",
    "WorkspaceLayout",
    "WorkspacePathError",
    "build_mcp_capability_inventory",
    "run_local_harness",
]
