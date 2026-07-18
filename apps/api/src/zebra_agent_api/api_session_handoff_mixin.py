from pathlib import Path

from agent_core.domain.session_handoff import HandoffActorKind

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_handoff import SessionHandoffApi


class ApiSessionHandoffMixin:
    database_path: Path

    def create_session_handoff(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        idempotency_key: str | None,
        principal_identity_hash: str,
        actor_kind: HandoffActorKind,
        preview: bool = False,
    ) -> ApiResponse:
        return SessionHandoffApi(self.database_path).create(
            session_id,
            payload,
            idempotency_key=idempotency_key,
            principal_identity_hash=principal_identity_hash,
            actor_kind=actor_kind,
            preview=preview,
        )

    def get_session_handoff(self, handoff_id: str) -> ApiResponse:
        return SessionHandoffApi(self.database_path).inspect(handoff_id)

    def get_session_lineage(self, session_id: str) -> ApiResponse:
        return SessionHandoffApi(self.database_path).lineage(session_id)
