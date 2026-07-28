from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_core.domain.context_continuation import (
    ProviderContinuationArtifact,
    ProviderContinuationRef,
)


@dataclass(frozen=True)
class LoadedProviderContinuation:
    artifact: ProviderContinuationArtifact
    opaque_payload: bytes


class ProviderContinuationStorePort(Protocol):
    def store(
        self,
        *,
        tenant_id: str,
        session_id: str,
        reference: ProviderContinuationRef,
        opaque_payload: bytes,
        maximum_ttl_seconds: int | None = None,
    ) -> ProviderContinuationArtifact: ...

    def load_compatible(
        self,
        artifact_id: str,
        *,
        tenant_id: str,
        provider: str,
        model_name: str,
        capability_version: str,
        as_of: datetime | None = None,
    ) -> LoadedProviderContinuation | None: ...

    def delete(
        self,
        artifact_id: str,
        *,
        tenant_id: str,
        deleted_at: datetime | None = None,
    ) -> ProviderContinuationArtifact | None: ...

    def sweep_expired(self, *, as_of: datetime | None = None) -> list[str]: ...
