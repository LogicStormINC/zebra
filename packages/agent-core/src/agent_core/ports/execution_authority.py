"""Ports for resolving and revalidating external Attempt authority."""

from typing import Protocol

from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionRequest,
    ExecutionAuthorityRevalidation,
    ExecutionAuthorityRevalidationRequest,
    ExecutionAuthoritySnapshot,
)


class ExecutionAuthorityResolverPort(Protocol):
    """Resolve short-lived authority without exposing credentials to Core."""

    def resolve_for_attempt(
        self,
        request: ExecutionAuthorityResolutionRequest,
    ) -> ExecutionAuthoritySnapshot: ...

    def revalidate_attempt(
        self,
        request: ExecutionAuthorityRevalidationRequest,
    ) -> ExecutionAuthorityRevalidation: ...
