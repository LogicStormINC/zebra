from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic

from agent_core.domain.modeling import ModelToolDefinition
from agent_tools import McpProxyRequest, McpProxyResponse
from agent_tools.mcp_proxy import McpProxyTransport

from agent_runtime.mcp_protocol import McpProtocolError


class McpHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"


class McpQuarantinedError(McpProtocolError):
    """Raised when a server is queried while quarantined inside its backoff window."""


@dataclass
class McpSessionPool:
    """Health-tracking wrapper around a single ``McpProxyTransport``.

    Phase A is a lightweight pool: stdio stays spawn-per-call (failure counts +
    bounded backoff), and HTTP relies on the transport's own connection
    handling. The pool classifies health (healthy/degraded/quarantined) and
    refuses to acquire a server that is within its quarantine backoff window.
    A successful call resets the failure counter; repeated failures escalate to
    quarantine with a bounded backoff schedule (no unbounded retry).
    """

    transport: McpProxyTransport
    max_failures: int = 3
    backoff_schedule: tuple[float, ...] = (1.0, 5.0, 30.0)
    clock: Callable[[], float] = field(default=monotonic, repr=False)
    _consecutive_failures: int = field(default=0, init=False)
    _health: McpHealthState = field(default=McpHealthState.HEALTHY, init=False)
    _quarantined_until: float = field(default=0.0, init=False)
    _quarantine_count: int = field(default=0, init=False)
    model_tools: tuple[ModelToolDefinition, ...] = field(default=(), init=False)

    def __post_init__(self) -> None:
        if self.max_failures < 1:
            raise ValueError("max_failures must be positive")
        if not self.backoff_schedule or any(wait <= 0 for wait in self.backoff_schedule):
            raise ValueError("backoff_schedule must be a non-empty sequence of positive waits")
        self.model_tools = tuple(getattr(self.transport, "model_tools", ()))

    @property
    def health(self) -> McpHealthState:
        return self._health

    def acquire(self) -> None:
        """Raise if the server is quarantined within its backoff window.

        If the window has elapsed, the server is allowed a probe call and moves
        out of quarantine (to degraded) for this attempt.
        """
        if self._health is McpHealthState.QUARANTINED:
            if self.clock() < self._quarantined_until:
                raise McpQuarantinedError(
                    "MCP server is quarantined within its backoff window"
                )
            self._health = McpHealthState.DEGRADED

    def release(self, *, success: bool) -> None:
        if success:
            self._consecutive_failures = 0
            self._health = McpHealthState.HEALTHY
            return
        self._consecutive_failures += 1
        if self._consecutive_failures < self.max_failures:
            self._health = McpHealthState.DEGRADED
            return
        self._health = McpHealthState.QUARANTINED
        slot = min(self._quarantine_count, len(self.backoff_schedule) - 1)
        self._quarantined_until = self.clock() + self.backoff_schedule[slot]
        self._quarantine_count += 1

    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        self.acquire()
        try:
            response = self.transport.execute(request)
        except Exception:
            self.release(success=False)
            raise
        self.release(success=True)
        return response

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if callable(close):
            close()
