from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.identifiers import SessionId

from zebra_agent_worker.claims import ClaimedSession, SessionClaimService


class SessionResumeError(ValueError):
    """Raised when a session cannot be resumed for execution."""


@dataclass(frozen=True)
class ResumedSession:
    claimed: ClaimedSession


class SessionResumeService:
    def __init__(self, claim_service: SessionClaimService) -> None:
        self._claim_service = claim_service

    def resume_session(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        resumed_at: datetime,
        lease_ttl_seconds: int,
    ) -> ResumedSession:
        claimed = self._claim_service.claim_session(
            session_id,
            worker_id=worker_id,
            claimed_at=resumed_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        if claimed.recovery.is_terminal:
            self._claim_service.release_claim(claimed)
            raise SessionResumeError("cannot resume terminal session")
        return ResumedSession(claimed=claimed)
