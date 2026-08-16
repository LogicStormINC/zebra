"""Shared typing for per-session execution authority wiring."""

from __future__ import annotations

from collections.abc import Callable

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.sessions import Session
from agent_core.ports.execution_authority import ExecutionAuthorityResolverPort

AuthorityScopeProvider = Callable[[Session], OpaqueAuthorityScope]
AuthorityResolver = ExecutionAuthorityResolverPort
AuthorityScope = OpaqueAuthorityScope

__all__ = [
    "AuthorityResolver",
    "AuthorityScope",
    "AuthorityScopeProvider",
]
