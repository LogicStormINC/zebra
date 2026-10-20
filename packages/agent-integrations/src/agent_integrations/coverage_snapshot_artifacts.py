"""Session-bound durable coverage Artifacts; existing corrupt data is never repaired."""

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from agent_core.domain.artifact_payloads import (
    ArtifactPayloadLifecycleStatus,
    ArtifactPayloadStatus,
    ArtifactPayloadWrite,
    StoredArtifactPayload,
)
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_persistence import canonical_coverage_bytes, coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import (
    ArtifactPayloadReadScopePort,
    ArtifactPayloadStorePort,
    BoundedArtifactPayloadReaderPort,
    ImmutableArtifactPayloadStorePort,
    VerifiedArtifactPayloadReaderPort,
)

from agent_integrations.coverage_snapshot_wire import Descriptor, parse, verify_manifest


def artifact_id(session: SessionId, binding: object) -> ArtifactId:
    return ArtifactId(
        uuid5(
            NAMESPACE_URL,
            "zebra.coverage/1:"
            + str(session)
            + ":"
            + sha256(canonical_coverage_bytes(binding)).hexdigest(),
        )
    )


class CoverageArtifacts:
    def __init__(
        self,
        store: ArtifactPayloadStorePort,
        session: SessionId,
        publication_lock: AbstractContextManager[object],
    ) -> None:
        self.store = store
        self.session = session
        self.publication_lock = publication_lock

    def load(
        self,
        identifier: ArtifactId,
        kind: str,
        maximum: int,
        now: datetime,
        *,
        mime_type: str = "application/octet-stream",
    ) -> tuple[str, bytes] | None:
        loaded = self.load_payload(identifier, kind, maximum, now, mime_type=mime_type)
        return None if loaded is None else (loaded[0].uri, loaded[1])

    def load_payload(
        self,
        identifier: ArtifactId,
        kind: str,
        maximum: int,
        now: datetime,
        *,
        mime_type: str = "application/octet-stream",
        expected_digest: str | None = None,
    ) -> tuple[StoredArtifactPayload, bytes] | None:
        """Return the same verified read's metadata, never a cross-read cache."""
        try:
            if isinstance(self.store, ArtifactPayloadReadScopePort):
                # No writes or MODEL calls inside this phase. The context exit
                # revalidates authority and full metadata before return is consumed.
                with self.store.read_payload_scope((identifier,)) as reader:
                    scoped = CoverageArtifacts(reader, self.session, self.publication_lock)
                    return scoped._load_payload(
                        identifier,
                        kind,
                        maximum,
                        now,
                        mime_type=mime_type,
                        expected_digest=expected_digest,
                    )
            return self._load_payload(
                identifier,
                kind,
                maximum,
                now,
                mime_type=mime_type,
                expected_digest=expected_digest,
            )
        except (OSError, ValueError) as exc:
            raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE) from exc

    def _load_payload(
        self,
        identifier: ArtifactId,
        kind: str,
        maximum: int,
        now: datetime,
        *,
        mime_type: str,
        expected_digest: str | None,
    ) -> tuple[StoredArtifactPayload, bytes] | None:
        reason = CoverageRefusalReason.ARTIFACT_UNAVAILABLE
        try:
            stored: StoredArtifactPayload | None
            direct = expected_digest is not None and isinstance(
                self.store, VerifiedArtifactPayloadReaderPort
            )
            if direct:
                assert isinstance(self.store, VerifiedArtifactPayloadReaderPort)
                assert expected_digest is not None
                # Known digest comes from the frozen caller bytes; the native Port
                # still checks fresh full records before/after physical I/O.
                stored, body = self.store.read_payload_verified_bounded(
                    identifier, session_id=self.session, digest=expected_digest, max_bytes=maximum
                )
            else:
                stored = self.store.get_payload(identifier)
            if stored is None:
                return None
            if (
                stored.artifact_id != identifier
                or stored.session_id != self.session
                or stored.kind != kind
                or stored.mime_type != mime_type
                or stored.uri != f"artifact://{identifier}"
                or stored.lifecycle_status != ArtifactPayloadLifecycleStatus.ACTIVE
                or stored.pruned_at is not None
                or stored.created_at.utcoffset() is None
                or stored.created_at > now
                or (
                    stored.retained_until is not None
                    and (stored.retained_until.utcoffset() is None or stored.retained_until <= now)
                )
                or type(stored.size_bytes) is not int
                or not 0 <= stored.size_bytes <= maximum
                or (expected_digest is not None and stored.sha256 != expected_digest)
            ):
                raise CoverageRefusedError(reason)
            if direct:
                pass  # Body and metadata belong to the same verified read above.
            elif isinstance(self.store, VerifiedArtifactPayloadReaderPort):
                # ponytail: the existing Port checks metadata and authority after
                # physical I/O; compare its full returned metadata, not just digest.
                verified, body = self.store.read_payload_verified_bounded(
                    identifier, session_id=self.session, digest=stored.sha256, max_bytes=maximum
                )
                if verified != stored:
                    raise CoverageRefusedError(reason)
            else:
                if not isinstance(self.store, BoundedArtifactPayloadReaderPort):
                    raise CoverageRefusedError(reason)
                body = self.store.read_payload_bytes_bounded(identifier, max_bytes=maximum)
                inspected = self.store.inspect_payload(identifier)
                if (
                    inspected is None
                    or inspected.artifact_id != identifier
                    or inspected.status != ArtifactPayloadStatus.AVAILABLE
                    or inspected.payload != stored
                ):
                    raise CoverageRefusedError(reason)
            if len(body) != stored.size_bytes or sha256(body).hexdigest() != stored.sha256:
                raise CoverageRefusedError(reason)
            return stored, body
        except (OSError, ValueError) as exc:
            raise CoverageRefusedError(reason) from exc

    def publish(
        self,
        identifier: ArtifactId,
        kind: str,
        body: bytes,
        maximum: int,
        validate: Callable[[], datetime],
        expires_at: datetime,
        *,
        mime_type: str = "application/octet-stream",
    ) -> str:
        # Store CAS is authoritative across processes; this legacy local lock only
        # avoids duplicate I/O within existing compositions.
        with self.publication_lock:
            return self._publish(
                identifier, kind, body, maximum, validate, expires_at, mime_type=mime_type
            )

    def _publish(
        self,
        identifier: ArtifactId,
        kind: str,
        body: bytes,
        maximum: int,
        validate: Callable[[], datetime],
        expires_at: datetime,
        *,
        mime_type: str = "application/octet-stream",
    ) -> str:
        now = validate()
        if len(body) > maximum:
            raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
        existing = self.load(identifier, kind, maximum, now, mime_type=mime_type)
        if existing is not None:
            if existing[1] != body:
                raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE)
            return existing[0]
        now = validate()
        try:
            if not isinstance(self.store, ImmutableArtifactPayloadStorePort):
                raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED)
            self.store.store_payload_immutable(
                ArtifactPayloadWrite(
                    session_id=self.session,
                    kind=kind,
                    mime_type=mime_type,
                    payload=body,
                    created_at=now,
                    retained_until=expires_at,
                ),
                artifact_id=identifier,
            )
        except (OSError, ValueError) as exc:
            raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE) from exc
        stored = self.load(identifier, kind, maximum, validate(), mime_type=mime_type)
        if stored is None or stored[1] != body:
            raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE)
        return stored[0]

    def manifest(
        self, identifier: ArtifactId, snapshot: Descriptor, maximum: int, now: datetime
    ) -> tuple[str, tuple[CoverageRecord, ...]] | None:
        stored = self.load(identifier, "coverage_manifest", maximum, now)
        if stored is None:
            return None
        try:
            data = json.loads(stored[1])
            if (
                not isinstance(data, dict)
                or set(data) != {"schema", "records"}
                or data["schema"] != "coverage-records/1"
                or not isinstance(data["records"], list)
                or len(data["records"]) != snapshot.record_count
            ):
                raise ValueError("manifest shape")
            records = tuple(
                parse(CoverageRecord, row, CoverageRefusalReason.MANIFEST_MISMATCH)
                for row in data["records"]
            )
            verify_manifest(snapshot, records)
            if coverage_manifest_bytes(records) != stored[1]:
                raise ValueError("manifest representation")
        except (ValueError, TypeError) as exc:
            raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE) from exc
        return stored[0], records
