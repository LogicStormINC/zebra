"""Runtime package for Zebra Agent."""

from agent_core.ports.runtime import (
    EffectiveRuntimeAuthority,
    RuntimeCapabilities,
    RuntimeCapabilityError,
    RuntimeClass,
    RuntimeHandle,
    RuntimeLimits,
    RuntimeSnapshot,
    SandboxSpec,
)

from agent_runtime.adapters.local import LocalRuntime
from agent_runtime.adapters.oci import OciRuntime
from agent_runtime.adapters.os_sandbox import OsSandboxRuntime
from agent_runtime.adapters.os_sandbox_platform import os_sandbox_engine
from agent_runtime.git_commit import (
    WorkspaceCommitCommand,
    WorkspaceCommitError,
    WorkspaceCommitResult,
    WorkspaceCommitService,
)
from agent_runtime.git_diff import WorkspaceDiffError, WorkspaceDiffResult, WorkspaceDiffService
from agent_runtime.harness import LocalToolGateway, run_local_harness
from agent_runtime.mcp_elicitation import (
    McpElicitationBridge,
    McpElicitationDisabledError,
)
from agent_runtime.mcp_http import StreamableHttpMcpTransport
from agent_runtime.mcp_inventory import (
    McpCapabilityInventory,
    McpServerCapability,
    McpToolCapability,
    build_mcp_capability_inventory,
    validate_mcp_capability_selection,
)
from agent_runtime.mcp_prompts import (
    McpPrompt,
    McpPromptArgument,
    McpPromptMessage,
    ResolvedMcpPrompt,
    discover_mcp_prompts,
    resolve_mcp_prompt,
)
from agent_runtime.mcp_protocol import (
    McpAnyServerSpec,
    McpHttpServerSpec,
    McpProtocolError,
    McpServerSpec,
)
from agent_runtime.mcp_resources import (
    McpResource,
    discover_mcp_resources,
    normalize_mcp_resource_ids,
    read_mcp_resource_attachments,
)
from agent_runtime.mcp_stdio import LocalStdioMcpTransport
from agent_runtime.research import (
    LocalResearchSubagentRunner,
    ReadOnlyToolGateway,
    ResearchSubagentTool,
)
from agent_runtime.setup_phase import (
    SetupPhaseError,
    SetupPhasePlan,
    SetupPhaseResult,
    SetupPhaseRunner,
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
from agent_runtime.workspace_quota import (
    WorkspaceQuotaError,
    WorkspaceQuotaEvidence,
    require_workspace_quota,
)

__all__ = [
    "LocalRuntime",
    "OciRuntime",
    "OsSandboxRuntime",
    "LocalResearchSubagentCoordinator",
    "LocalResearchSubagentRunner",
    "LocalToolGateway",
    "LocalStdioMcpTransport",
    "LocalWorkspace",
    "LocalWorktree",
    "McpCapabilityInventory",
    "McpElicitationBridge",
    "McpElicitationDisabledError",
    "McpHttpServerSpec",
    "McpAnyServerSpec",
    "McpServerCapability",
    "McpToolCapability",
    "ReadOnlyToolGateway",
    "ResearchSubagentTool",
    "RuntimeCapabilityError",
    "RuntimeCapabilities",
    "RuntimeClass",
    "RuntimeLimits",
    "EffectiveRuntimeAuthority",
    "RuntimeHandle",
    "RuntimeSnapshot",
    "SandboxSpec",
    "StreamableHttpMcpTransport",
    "McpProtocolError",
    "McpPrompt",
    "McpPromptArgument",
    "McpPromptMessage",
    "McpResource",
    "McpServerSpec",
    "ResolvedMcpPrompt",
    "SubagentLimitError",
    "SetupPhaseError",
    "SetupPhasePlan",
    "SetupPhaseResult",
    "SetupPhaseRunner",
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
    "WorkspaceQuotaError",
    "WorkspaceQuotaEvidence",
    "build_mcp_capability_inventory",
    "discover_mcp_resources",
    "discover_mcp_prompts",
    "normalize_mcp_resource_ids",
    "read_mcp_resource_attachments",
    "resolve_mcp_prompt",
    "validate_mcp_capability_selection",
    "run_local_harness",
    "os_sandbox_engine",
    "require_workspace_quota",
]
