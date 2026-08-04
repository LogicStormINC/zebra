from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import WorkspaceBindingRevision
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority


@dataclass(frozen=True, slots=True)
class HandoffDispatch:
    delivery_id: str
    child_session_id: SessionId
    handoff_id: HandoffId
    status: str
    claimed_by: str | None = None
    claim_token: str | None = None
    claim_fence: LeaseFence | None = None
    claim_expires_at: datetime | None = None
    operation_id: str | None = None
    expected_stream_revision: int | None = None
    expected_pointer_revision: int | None = None
    authority: WorkerMutationAuthority | None = None

    @property
    def mutation_authority(self) -> WorkerMutationAuthority | None:
        """Compatibility name for callers that spell out the authority type."""
        return self.authority


class HandoffDispatchStorePort(Protocol):
    def claim_for_child(
        self,
        child_session_id: SessionId,
        *,
        fence: LeaseFence,
        claimed_at: datetime,
        lease_seconds: int = 60,
    ) -> HandoffDispatch | None: ...

    def acknowledge(self, claim: HandoffDispatch, *, checked_at: datetime) -> None: ...

    def acknowledge_if_workspace_matches(
        self,
        claim: HandoffDispatch,
        *,
        expected: WorkspaceBindingRevision,
        checked_at: datetime,
    ) -> WorkspaceBindingRevision: ...


class FencedHandoffDispatchStorePort(HandoffDispatchStorePort, Protocol):
    """Cloud dispatch extension; local SQLite keeps the legacy Port shape."""

    def claim_for_child(
        self,
        child_session_id: SessionId,
        *,
        fence: LeaseFence | None = None,
        authority: WorkerMutationAuthority | None = None,
        operation_id: str | None = None,
        expected_stream_revision: int | None = None,
        expected_pointer_revision: int | None = None,
        claimed_at: datetime,
        lease_seconds: int = 60,
    ) -> HandoffDispatch | None: ...
