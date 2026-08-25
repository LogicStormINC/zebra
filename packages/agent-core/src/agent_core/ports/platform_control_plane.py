"""Platform-level control-plane store bundle contract (ADR-CLIENT-01).

API and Worker compose the SAME bundle instead of hand-building adapters
from a DSN. Client stores are optional: the client integration feature
flag is default-off and a disabled bundle carries ``None`` stores while
all existing host, orchestration and memory behavior stays unchanged.
"""

from dataclasses import dataclass
from typing import Protocol

from agent_core.ports.agent_registry import AgentRegistryPort
from agent_core.ports.client_capability_registry import ClientCapabilityRegistryPort
from agent_core.ports.client_control_lease import ClientControlLeasePort
from agent_core.ports.client_effect_dispatch import ClientEffectDispatchPort
from agent_core.ports.client_effect_receipts import ClientEffectReceiptPort
from agent_core.ports.client_session_registry import ClientSessionRegistryPort


class _DelegationStore(Protocol):
    """Structural stand-in for the durable subagent delegation store."""


class _MailboxStore(Protocol):
    """Structural stand-in for the agent mailbox store."""


class _OrchestrationStore(Protocol):
    """Structural stand-in for the orchestration projection store."""


@dataclass(frozen=True, slots=True)
class AgentPlatformControlPlane:
    deployment_namespace: str
    host_authorities: object | None = None
    host_connectors: object | None = None
    frontend_capabilities: ClientCapabilityRegistryPort | None = None
    client_sessions: ClientSessionRegistryPort | None = None
    client_control_leases: ClientControlLeasePort | None = None
    client_effects: ClientEffectDispatchPort | None = None
    client_effect_receipts: ClientEffectReceiptPort | None = None
    agent_registry: AgentRegistryPort | None = None
    orchestration: _OrchestrationStore | None = None
    delegation: _DelegationStore | None = None
    mailbox: _MailboxStore | None = None

    def __post_init__(self) -> None:
        namespace = self.deployment_namespace
        if not namespace.strip() or len(namespace) > 255:
            raise ValueError("deployment namespace must be trimmed and bounded")
        if namespace != self.deployment_namespace.strip():
            raise ValueError("deployment namespace must be trimmed")

    def require_client_stores(self) -> None:
        """Cloud startup fails closed when client integration needs stores."""

        missing = [
            name
            for name, store in (
                ("frontend_capabilities", self.frontend_capabilities),
                ("client_sessions", self.client_sessions),
                ("client_control_leases", self.client_control_leases),
                ("client_effects", self.client_effects),
                ("client_effect_receipts", self.client_effect_receipts),
            )
            if store is None
        ]
        if missing:
            raise ValueError(
                "client integration is enabled but platform stores are"
                f" missing: {', '.join(missing)}"
            )
