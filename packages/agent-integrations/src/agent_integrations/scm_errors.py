class ScmIntegrationError(ValueError):
    """Raised when SCM data cannot be read."""


class ScmUnavailableError(ValueError):
    """Raised when a networked SCM action is unavailable."""
