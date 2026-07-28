from __future__ import annotations

from pathlib import Path

from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_artifact_control import SessionArtifactControlApi
from zebra_agent_api.session_read import SessionReadApi


class ApiArtifactReadMixin:
    database_path: Path
    stores: ControlPlaneStores

    def get_session_artifacts(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_artifacts(session_id)

    def get_session_artifact_detail(self, session_id: str, artifact_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_artifact_detail(
            session_id,
            artifact_id,
        )

    def get_session_artifact_content(self, session_id: str, artifact_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_artifact_content(
            session_id,
            artifact_id,
        )

    def prune_session_artifact(self, session_id: str, artifact_id: str) -> ApiResponse:
        return SessionArtifactControlApi(self.database_path, self.stores).prune_artifact(
            session_id,
            artifact_id,
        )

    def get_session_delivery_audit(self, session_id: str) -> ApiResponse:
        return SessionReadApi(self.database_path, self.stores).get_session_delivery_audit(
            session_id
        )
