"""Actual Worker native checker with lock-free, same-database proof preparation."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast

from agent_core.domain.artifact_payloads import StoredArtifactPayload
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_transaction_support import lock_payload
from agent_storage.postgres.connection_scope import postgres_connection_scope
from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.coverage_recovery_preparation import (
    PreparedCoverageRecovery,
    RecoveryReadSnapshot,
    _digest,
)


class RecoveryArtifactReads:
    """Pin the reader's physically verified receipt to the same native snapshot."""

    def __init__(self, artifacts: Any, connection: Any, originals: dict[str, tuple[Any, bytes]]):
        self.artifacts, self.connection, self.originals = artifacts, connection, originals
        self._bodies: dict[str, bytes] = {}
        self._size = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.artifacts, name)

    def read_payload_bytes_bounded(self, artifact_id: Any, *, max_bytes: int) -> bytes:
        return self._read_record(artifact_id, max_bytes=max_bytes)[1]

    def read_payload_verified_bounded(
        self, artifact_id: ArtifactId, *, session_id: SessionId, digest: str, max_bytes: int
    ) -> tuple[StoredArtifactPayload, bytes]:
        if session_id != self.artifacts.binding.session_id:
            raise ValueError("prepared Artifact belongs to another Session")
        record, body = self._read_record(artifact_id, max_bytes=max_bytes, digest=digest)
        return self.artifacts._stored(record), body

    def _read_record(
        self, artifact_id: Any, *, max_bytes: int, digest: str | None = None
    ) -> tuple[Any, bytes]:
        if type(max_bytes) is not int or not 0 <= max_bytes <= MAX_COVERAGE_ARTIFACT_BYTES:
            raise ValueError("invalid prepared Artifact read bound")
        record = artifact_payload_from_row(
            lock_payload(
                self.connection,
                self.artifacts.deployment,
                artifact_id,
                self.artifacts.binding.session_id,
            )
        )
        if (
            record is None
            or record.lifecycle_status != CloudArtifactPayloadLifecycleStatus.FINALIZED
            or record.object_receipt is None
            or record.reservation.size_bytes > max_bytes
            or (digest is not None and record.reservation.sha256 != digest)
        ):
            raise ValueError("prepared original lifecycle or byte bound conflicts")
        if self.artifacts._record(artifact_id) != record:
            raise ValueError("prepared physical object version differs from native metadata")
        key = str(artifact_id)
        previous = self.originals.get(key)
        if previous is not None and previous[0] != record:
            raise ValueError("prepared original version or bytes changed")
        data = self._bodies.get(key)
        if data is None:
            data = self.artifacts._read_payload_bytes_for_record(
                artifact_id, record, max_bytes=max_bytes
            )
        elif self.artifacts._record(artifact_id) != record:
            raise ValueError("prepared physical object version changed during verification")
        if len(data) != record.reservation.size_bytes or len(data) > max_bytes:
            raise ValueError("prepared original byte bound conflicts")
        actual_digest = sha256(data)
        if actual_digest.hexdigest() != record.reservation.sha256:
            raise ValueError("prepared original bytes disagree with reservation")
        value = (record, actual_digest.digest())
        previous = self.originals.setdefault(key, value)
        if previous != value:
            raise ValueError("prepared original version or bytes changed")
        # ponytail: same preparation only; fresh full native/physical metadata each
        # use, independent final object reread. Beyond 32 MiB, fall back to I/O.
        if key not in self._bodies and self._size + len(data) <= MAX_COVERAGE_ARTIFACT_BYTES:
            self._bodies[key] = data
            self._size += len(data)
        return record, cast(bytes, data)

    def read_payload_bytes(self, artifact_id: Any) -> bytes:
        return self.read_payload_bytes_bounded(artifact_id, max_bytes=32 * 1024 * 1024)


@dataclass(frozen=True)
class NativeCoverageRecoveryCheck:
    runtime: Any
    service: Any
    execution_authority: PostgresCoverageAuthority | None = None

    def __call__(
        self, connection: Any, namespace: str, pending: Any, receipt: Any
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.runtime.recovery_check(self.service, connection, namespace, pending, receipt),
        )

    def prepare(self, namespace: str, event_id: Any) -> Any:
        return self._prepare(namespace, event_id, continuation=False)

    def prepare_continuation(self, namespace: str, event_id: Any) -> Any:
        return self._prepare(namespace, event_id, continuation=True)

    @postgres_connection_scope()
    def _prepare(self, namespace: str, event_id: Any, *, continuation: bool) -> Any:
        if namespace != self.runtime.deployment_namespace:
            raise ValueError("recovery preparation namespace conflicts")
        with self.runtime.metadata._database.connect() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.execute("SET LOCAL statement_timeout = '5s'")
            snapshot = RecoveryReadSnapshot(connection, reuse_reads=True)
            snapshot.bind_database()
            pending = snapshot.execute(
                "SELECT * FROM session_command_pending WHERE deployment_namespace=%s "
                "AND accepted_event_id=%s",
                (namespace, event_id),
            ).fetchone()
            if pending is None:
                raise ValueError("recovery preparation command is unavailable")
            receipt = snapshot.execute(
                "SELECT * FROM command_handoff_receipts WHERE deployment_namespace=%s "
                "AND scope_key=%s AND command_id=%s",
                (namespace, pending["scope_key"], pending["command_id"]),
            ).fetchone()
            if receipt is None or receipt["handled_event_id"] is not None:
                return self
            from zebra_agent_worker.coverage_recovery import verify_cloud_coverage_recovery

            finalizers: list[Any] = []
            proof = verify_cloud_coverage_recovery(
                self.runtime,
                self.service,
                snapshot,
                namespace,
                pending,
                receipt,
                finalizers=finalizers,
                continuation=continuation,
                execution_authority=self.execution_authority if continuation else None,
            )
            if len(finalizers) != 1:
                raise ValueError("native recovery preparation requires final authority validation")
            stamp = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        snapshot.cached_reads.clear()
        snapshot.cached_bytes = 0
        return PreparedCoverageRecovery(
            namespace, _digest(pending), _digest(receipt), snapshot, proof, stamp, finalizers[0]
        )
