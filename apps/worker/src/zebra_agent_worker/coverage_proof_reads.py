"""Private locked proof-phase reads; not public per-getter revocation equivalence."""

from datetime import UTC, datetime
from typing import Any

from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_core.domain.identifiers import ArtifactId
from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.artifact_payload_transaction_support import lock_payload
from agent_storage.postgres.coverage_proof_prefetch import locked_page, materialized_sources

from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts


class LockedCoverageProofReads(CloudCoverageArtifacts):
    def __init__(
        self, source: CloudCoverageArtifacts, connection: Any, *, reuse_records: bool = False
    ) -> None:
        super().__init__(
            binding=source.binding,
            deployment_namespace=source.deployment,
            metadata=source.metadata,
            objects=source.objects,
            publisher=source.publisher,
            authority=source.authority,
            check_authority=source.check_authority,
            sync_events=source.sync_events,
        )
        self._proof_connection: Any = connection
        self._source = source
        self._reuse_records = reuse_records
        self._proof_records: dict[ArtifactId, CloudArtifactPayloadRecord] = {}
        self._proof_rows: dict[ArtifactId, dict[str, Any]] = {}
        self._proof_events: dict[ArtifactId, list[Any]] = {}
        self._proof_deadlines: list[datetime] = []

    def _defer_checkpoint_retention(self, connection: Any, deadlines: list[datetime]) -> bool:
        if self._proof_connection is None:
            raise RuntimeError("locked Artifact proof scope has ended")
        if connection is not self._proof_connection:
            raise ValueError("locked Artifact transaction identity conflicts")
        if not self._reuse_records:
            return False
        if deadlines:
            earliest = min(deadlines)
            self._proof_deadlines[:] = [
                min(self._proof_deadlines[0], earliest) if self._proof_deadlines else earliest
            ]
        return True

    def _finish_retention(self) -> None:
        from agent_storage.postgres.coverage_model_checkpoint import check_checkpoint_retention

        if self._proof_deadlines:
            check_checkpoint_retention(self._proof_connection, self._proof_deadlines)

    def _prefetch_proof(self, identifiers: tuple[ArtifactId, ...]) -> None:
        if self._proof_connection is None:
            raise RuntimeError("locked Artifact proof scope has ended")
        if not self._reuse_records:
            return
        pending = tuple(
            identifier
            for identifier in identifiers
            if identifier not in self._proof_rows or identifier not in self._proof_events
        )
        if not pending:
            return
        # ponytail: the scope holds at most 8192 identities. Larger transcripts
        # keep bounded pages and fall back to original per-object native proof.
        if len(set(self._proof_rows).union(pending)) > 8192:
            return
        rows, events = locked_page(self._proof_connection, self.deployment, self.binding, pending)
        by_ref: dict[str, list[Any]] = {}
        by_event = {event["event_id"]: event for event in events}
        for event in events:
            if event["event_type"] == "coverage_artifact_materialized":
                metadata = event["payload"].get("metadata")
                ref = metadata.get("artifact_uri") if isinstance(metadata, dict) else None
                if isinstance(ref, str):
                    by_ref.setdefault(ref, []).append(event)
        for identifier, row in rows.items():
            sources = {
                event["event_id"]: event for event in by_ref.get(f"artifact://{identifier}", [])
            }
            if row["event_id"] in by_event:
                sources[row["event_id"]] = by_event[row["event_id"]]
            self._proof_events[identifier] = list(sources.values())
        self._proof_rows.update(rows)

    def _native_materialized_sources(
        self,
        connection: Any,
        deployment: str,
        session_id: Any,
        ref: str,
        *,
        event_id: Any = None,
    ) -> list[Any]:
        from agent_storage.postgres.coverage_artifacts import _identity

        if self._proof_connection is None:
            raise RuntimeError("locked Artifact proof scope has ended")
        if (
            connection is not self._proof_connection
            or deployment != self.deployment
            or session_id != self.binding.session_id
        ):
            raise ValueError("locked Artifact transaction identity conflicts")
        sources = self._proof_events.get(_identity(ref))
        if self._reuse_records and sources is not None:
            return [
                event
                for event in sources
                if event["event_id"] == event_id
                or (
                    event["event_type"] == "coverage_artifact_materialized"
                    and isinstance(event["payload"].get("metadata"), dict)
                    and event["payload"]["metadata"].get("artifact_uri") == ref
                )
            ]
        return materialized_sources(
            None,
            connection,
            deployment,
            self.binding,
            ref,
            event_id=event_id,
        )

    def _native_payload_row(
        self,
        connection: Any,
        deployment: str,
        artifact_id: ArtifactId,
        session_id: Any,
    ) -> dict[str, Any]:
        if self._proof_connection is None:
            raise RuntimeError("locked Artifact proof scope has ended")
        if (
            connection is not self._proof_connection
            or deployment != self.deployment
            or session_id != self.binding.session_id
        ):
            raise ValueError("locked Artifact transaction identity conflicts")
        previous = self._proof_rows.get(artifact_id) if self._reuse_records else None
        if previous is not None:
            return previous
        row = lock_payload(connection, deployment, artifact_id, session_id)
        if self._reuse_records and len(self._proof_rows) < 8192:
            self._proof_rows[artifact_id] = row
        return row

    def _record(self, artifact_id: ArtifactId) -> CloudArtifactPayloadRecord | None:
        if self._proof_connection is None:
            raise RuntimeError("locked Artifact proof scope has ended")
        previous = self._proof_records.get(artifact_id)
        # ponytail: only the known pure deriver enables reuse. Its verifier never
        # writes metadata or releases this transaction's FOR UPDATE pins. Other
        # derivers reread; physical I/O and scope exit still check fresh authority.
        record = (
            previous
            if self._reuse_records and previous is not None
            else (
                artifact_payload_from_row(
                    self._native_payload_row(
                        self._proof_connection,
                        self.deployment,
                        artifact_id,
                        self.binding.session_id,
                    )
                )
            )
        )
        if previous is not None and previous != record:
            raise ValueError("locked Artifact full record or object version changed")
        # ponytail: bound identity retention, not commit eligibility. Overflow
        # falls back to the original per-getter authority/metadata path.
        if previous is None and len(self._proof_records) >= 8192:
            if self._source._record(artifact_id) != record:
                raise ValueError("locked Artifact disagrees with guarded metadata")
        else:
            self._proof_records[artifact_id] = record
        if (
            record.reservation.retained_until is not None
            and record.reservation.retained_until <= datetime.now(UTC)
        ):
            return None
        return record

    def _read_payload_bytes_for_record(
        self, artifact_id: ArtifactId, record: CloudArtifactPayloadRecord | None, *, max_bytes: int
    ) -> bytes:
        if self._proof_connection is None:
            raise RuntimeError("locked Artifact proof scope has ended")
        previous = (
            self._verified_payload_owner._verified_payloads.get(artifact_id)
            if self.reuse_verified_payloads
            else None
        )
        if self._reuse_records and previous is not None and previous[0] == record:
            # Only CPU work on verified immutable bytes remains in this phase.
            return super()._read_payload_bytes_for_record(artifact_id, record, max_bytes=max_bytes)
        # Physical I/O is an external boundary even in a pure proof operation.
        # A revocation during object one must refuse before reading object two.
        self.check_authority()
        body = super()._read_payload_bytes_for_record(artifact_id, record, max_bytes=max_bytes)
        self.check_authority()
        return body

    def store_payload_immutable(self, *args: Any, **kwargs: Any) -> Any:
        raise ValueError("locked proof reader cannot publish Artifacts")

    def store_payloads_immutable(self, *args: Any, **kwargs: Any) -> Any:
        raise ValueError("locked proof reader cannot publish Artifacts")
