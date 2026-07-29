from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import WorkspaceBindingRevision


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
