from pathlib import Path

from agent_core.domain.session_handoff import HandoffActorKind
from agent_core.ports import EffectStateReadPort
from agent_storage import ControlPlaneStores
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_handoff import SessionHandoffApi


class ApiSessionHandoffMixin:
    database_path: Path
    stores: ControlPlaneStores
    settings: ZebraAgentSettings
    effect_state: EffectStateReadPort | None

    def _session_handoff_api(self) -> SessionHandoffApi:
        return SessionHandoffApi(
            self.database_path,
            self.stores,
            effect_state=self.effect_state,
        )

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
        if not self.settings.session_handoff.enabled:
            return ApiResponse(
                409,
                {
                    "session_id": session_id,
                    "status": "handoff_disabled",
                    "reason": "session handoff is disabled by operator configuration",
                },
            )
        return self._session_handoff_api().create(
            session_id,
            payload,
            idempotency_key=idempotency_key,
            principal_identity_hash=principal_identity_hash,
            actor_kind=actor_kind,
            preview=preview,
        )

    def get_session_handoff(self, handoff_id: str) -> ApiResponse:
        return self._session_handoff_api().inspect(handoff_id)

    def get_session_lineage(self, session_id: str) -> ApiResponse:
        return self._session_handoff_api().lineage(session_id)
