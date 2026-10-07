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
)
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_persistence import canonical_coverage_bytes, coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort

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
        self, identifier: ArtifactId, kind: str, maximum: int, now: datetime
    ) -> tuple[str, bytes] | None:
        reason = CoverageRefusalReason.ARTIFACT_UNAVAILABLE
        try:
            stored = self.store.get_payload(identifier)
            if stored is None:
                return None
            if (
                stored.artifact_id != identifier
                or stored.session_id != self.session
                or stored.kind != kind
                or stored.mime_type != "application/octet-stream"
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
            ):
                raise CoverageRefusedError(reason)
            body = self.store.read_payload_bytes(identifier)
            inspected = self.store.inspect_payload(identifier)
            if (
                inspected is None
                or inspected.artifact_id != identifier
                or inspected.status != ArtifactPayloadStatus.AVAILABLE
                or inspected.payload != stored
                or len(body) != stored.size_bytes
                or sha256(body).hexdigest() != stored.sha256
            ):
                raise CoverageRefusedError(reason)
            return stored.uri, body
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
    ) -> str:
        # ponytail: composition must share this lock across ALL publishers of this
        # store. It serializes publication within one process; multiple processes
        # require a single writer or an atomic create-if-absent store contract.
        # ArtifactPayloadStorePort cannot protect against writers outside this lock.
        with self.publication_lock:
            return self._publish(identifier, kind, body, maximum, validate, expires_at)

    def _publish(
        self,
        identifier: ArtifactId,
        kind: str,
        body: bytes,
        maximum: int,
        validate: Callable[[], datetime],
        expires_at: datetime,
    ) -> str:
        now = validate()
        if len(body) > maximum:
            raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
        existing = self.load(identifier, kind, maximum, now)
        if existing is not None:
            if existing[1] != body:
                raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE)
            return existing[0]
        now = validate()
        try:
            self.store.store_payload(
                ArtifactPayloadWrite(
                    session_id=self.session,
                    kind=kind,
                    mime_type="application/octet-stream",
                    payload=body,
                    created_at=now,
                    retained_until=expires_at,
                ),
                artifact_id=identifier,
            )
        except (OSError, ValueError) as exc:
            raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE) from exc
        stored = self.load(identifier, kind, maximum, validate())
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
