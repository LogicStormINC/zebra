"""Public exports load on demand; direct submodule imports stay bounded."""

# ruff: noqa: F405 -- TYPE_CHECKING exports and __getattr__ define the public names.

from importlib import import_module as _import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._public_exports import *  # noqa: F403

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
    "WorkspaceMaterializationError",
    "WorkspaceProvisionerError",
    "PostgresWorkspaceProvisioner",
    "materialize_archive",
    "materialize_git",
    "materialize_snapshot_bytes",
    "workspace_tree_digest",
    "WorkspaceRuntimeResolver",
    "WorkspaceRuntimeResolutionError",
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


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # ponytail: first public access loads the original aggregate; per-name lazy
    # exports are only needed if aggregate consumers also need lower startup cost.
    value = getattr(_import_module(f"{__name__}._public_exports"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
