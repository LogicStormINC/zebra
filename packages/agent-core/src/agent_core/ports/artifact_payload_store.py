from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol, runtime_checkable

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadInspection,
    ArtifactPayloadWrite,
    StoredArtifactPayload,
)
from agent_core.domain.identifiers import ArtifactId, SessionId


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


@runtime_checkable
class ImmutableArtifactPayloadStorePort(Protocol):
    """Optional immutable publication capability, independent of legacy callers."""

    def store_payload_immutable(
        self,
        payload: ArtifactPayloadWrite,
        *,
        artifact_id: ArtifactId,
    ) -> StoredArtifactPayload:
        """Publish once; exact metadata/byte retries succeed, conflicts fail closed."""
        ...


@runtime_checkable
class ImmutableArtifactPayloadBatchStorePort(Protocol):
    """Optional bounded publication; local single-object behavior is unchanged."""

    def store_payloads_immutable(
        self, payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...],
    ) -> tuple[StoredArtifactPayload, ...]:
        """Verify exact bytes outside transactions, atomically finalize the whole batch.

        Return records in input order. Refuse duplicate IDs, conflicting retries,
        expired retention, more than 1000 objects or 32 MiB total. Upload failures
        may leave staged objects, never partially finalized new evidence.
        """
        ...


@runtime_checkable
class BoundedArtifactPayloadReaderPort(Protocol):
    """Optional physically bounded, integrity-verified payload read capability."""

    def read_payload_bytes_bounded(self, artifact_id: ArtifactId, *, max_bytes: int) -> bytes:
        """Read at most max_bytes+1 physically; verify actual length and digest."""
        ...


@runtime_checkable
class VerifiedArtifactPayloadReaderPort(Protocol):
    """One bounded read with fresh pre/post authority and exact metadata binding."""

    def read_payload_verified_bounded(
        self, artifact_id: ArtifactId, *, session_id: SessionId, digest: str, max_bytes: int
    ) -> tuple[StoredArtifactPayload, bytes]:
        """Reject scope/digest before I/O; return metadata checked again after I/O."""
        ...


@runtime_checkable
class ArtifactPayloadReadScopePort(Protocol):
    """Optional bounded readonly phase; no model calls or writes inside the scope."""

    def read_payload_scope(
        self, artifact_ids: tuple[ArtifactId, ...],
    ) -> AbstractContextManager[ArtifactPayloadStorePort]:
        """At most 1000 unique IDs and 32 MiB total, including unavailable IDs.

        Verify authority and all exact lifecycle metadata before entry and after
        reads. Do not consume/commit results until successful scope exit. No
        database transaction created by coalescing survives object I/O; escaped
        prepared readers refuse access. Inapplicable/already-owned proof scopes
        may yield the original guarded reader, without coalescing or claiming
        unlocked I/O. This must not create a new transaction across object I/O.
        """
        ...
