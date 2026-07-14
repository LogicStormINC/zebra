class ToolRegistryError(ValueError):
    """Base error for tool registry and execution validation."""


class UnknownToolError(ToolRegistryError):
    """Raised when a tool call references an unregistered tool."""


class ToolArgumentError(ToolRegistryError):
    """Raised when a tool call does not satisfy its contract."""


class McpProxyTransportError(ToolRegistryError):
    """Raised when an MCP proxy request cannot be executed safely."""
