class ScmIntegrationError(ValueError):
    """Raised when SCM data cannot be read."""


class ScmUnavailableError(ValueError):
    """Raised when a networked SCM action is unavailable."""

    def __init__(
        self,
        message: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.metadata = metadata or {}
