from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId


@dataclass(frozen=True)
class StoredContextCapsule:
    artifact_id: ArtifactId
    session_id: SessionId
    capsule: ContextCapsule
    payload_sha256: str
    event: SessionEvent
    compaction_event: SessionEvent | None = None


class ContextLifecycleStorePort(Protocol):
    def persist_capsule_and_advance(
        self,
        *,
        session_id: SessionId,
        capsule: ContextCapsule,
        validation_context: ContextCapsuleValidationContext,
        sequence: int,
        expected_active_capsule_id: str | None,
        compaction_event: SessionEvent | None = None,
        created_at: datetime | None = None,
    ) -> StoredContextCapsule: ...

    def get_capsule(self, capsule_id: str) -> StoredContextCapsule | None: ...

    def get_active_capsule(self, session_id: SessionId) -> StoredContextCapsule | None: ...

    def activate_capsule(
        self,
        *,
        session_id: SessionId,
        capsule_id: str,
        expected_active_capsule_id: str | None,
        event: SessionEvent,
    ) -> StoredContextCapsule: ...
