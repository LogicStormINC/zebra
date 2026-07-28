from datetime import datetime
from typing import Protocol

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadInspection,
    ArtifactPayloadWrite,
    StoredArtifactPayload,
)
from agent_core.domain.identifiers import ArtifactId


class ArtifactPayloadStorePort(Protocol):
    def store_payload(
        self,
        payload: ArtifactPayloadWrite,
        *,
        artifact_id: ArtifactId | None = None,
    ) -> StoredArtifactPayload: ...

    def get_payload(self, artifact_id: ArtifactId) -> StoredArtifactPayload | None: ...

    def inspect_payload(self, artifact_id: ArtifactId) -> ArtifactPayloadInspection | None: ...

    def prune_payload(
        self,
        artifact_id: ArtifactId,
        *,
        pruned_at: datetime | None = None,
    ) -> StoredArtifactPayload | None: ...

    def sweep_expired_payloads(
        self,
        *,
        as_of: datetime | None = None,
    ) -> list[StoredArtifactPayload]: ...

    def read_payload_bytes(self, artifact_id: ArtifactId) -> bytes: ...
