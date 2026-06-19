class WorkspaceError(ValueError):
    """Base error for workspace lifecycle and path validation."""


class WorkspacePathError(WorkspaceError):
    """Raised when a path is invalid for the current workspace boundary."""
