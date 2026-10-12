"""Bounded readonly execution phase; fresh bulk metadata at both boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_core.domain.identifiers import ArtifactId
from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.work_unit import postgres_work_unit

from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts


def native_metadata(
    source: CloudCoverageArtifacts, identifiers: tuple[ArtifactId, ...],
) -> dict[ArtifactId, CloudArtifactPayloadRecord] | None:
    from agent_storage.postgres.work_unit import borrow_work_unit

    from zebra_agent_worker.coverage_native_model import (
        _closure,
        _worker_guard,
        qualified_final_reads,
    )

    reader = source._metadata_reader
    if (not _worker_guard(reader, "read_metadata") or not qualified_final_reads(source)
            or borrow_work_unit((source.metadata._database._dsn, source.deployment)) is not None):
        return None
    cells = _closure(reader)
    local = _closure(source.check_local_authority).get("check_local_native")
    native = _closure(local)
    if (cells.get("execution_authority") is not native.get("execution_authority")
            or cells.get("ownership_check") is not native.get("ownership_check")
            or cells.get("check_external") is not source.check_external_authority
            or cells.get("validate_local_entry") is not native.get("validate_local_entry")):
        return None
    assert callable(reader)
    return reader(identifiers)


def metadata_batch(
    source: CloudCoverageArtifacts,
    identifiers: tuple[ArtifactId, ...],
) -> dict[ArtifactId, CloudArtifactPayloadRecord]:
    if source.deployment != source.metadata._database.deployment_namespace:
        raise ValueError("prepared Artifact deployment conflicts with metadata adapter")
    observed = native_metadata(source, identifiers)
    if observed is not None:
        return observed
    local, external = source.check_local_authority, source.check_external_authority
    if local is not None and external is not None:
        external()
    else:
        source.check_authority()
    with postgres_work_unit(source.metadata._database) if local is not None else nullcontext():
        if local is not None:
            local()
        with source.metadata._database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM artifact_payload_metadata WHERE deployment_namespace=%s
                   AND session_id=%s AND artifact_id=ANY(%s)""",
                (source.deployment, source.binding.session_id, list(identifiers)),
            ).fetchall()
    records = {row["artifact_id"]: artifact_payload_from_row(row) for row in rows}
    selected = frozenset(identifiers)
    if any(
        record.artifact_id not in selected or record.session_id != source.binding.session_id
        for record in records.values()
    ):
        raise ValueError("prepared Artifact metadata scope conflicts")
    if sum(record.reservation.size_bytes for record in records.values()) > 32 * 1024 * 1024:
        raise ValueError("prepared Artifact read exceeds cumulative bound")
    return records


@contextmanager
def prepared_reads(
    source: CloudCoverageArtifacts,
    identifiers: tuple[ArtifactId, ...],
) -> Iterator[CloudCoverageArtifacts]:
    if (
        not isinstance(identifiers, tuple)
        or not 1 <= len(identifiers) <= 1000
        or any(not isinstance(identifier, UUID) for identifier in identifiers)
        or len(set(identifiers)) != len(identifiers)
    ):
        raise ValueError("invalid prepared Artifact read identity set")
    from agent_storage.postgres.work_unit import borrow_work_unit

    if borrow_work_unit((source.metadata._database._dsn, source.deployment)) is not None:
        raise ValueError("prepared execution reads cannot borrow a locked transaction")
    records = metadata_batch(source, identifiers)
    reader = PreparedCoverageReads(source, identifiers, records)
    try:
        yield reader
        if metadata_batch(source, identifiers) != records:
            raise ValueError("prepared Artifact metadata changed during read phase")
        now = datetime.now(UTC)
        if any(
            record.reservation.retained_until is not None
            and record.reservation.retained_until <= now
            for record in records.values()
        ):
            raise ValueError("prepared Artifact retention expired during read phase")
    finally:
        reader._records = None


class PreparedCoverageReads(CloudCoverageArtifacts):
    def __init__(
        self,
        source: CloudCoverageArtifacts,
        identifiers: tuple[ArtifactId, ...],
        records: dict[ArtifactId, CloudArtifactPayloadRecord],
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
        self._identifiers = frozenset(identifiers)
        self._records: dict[ArtifactId, CloudArtifactPayloadRecord] | None = records
        self.reuse_verified_payloads = source.reuse_verified_payloads
        self._verified_payload_owner = source

    def _record(self, artifact_id: ArtifactId) -> CloudArtifactPayloadRecord | None:
        if self._records is None:
            raise RuntimeError("prepared Artifact read scope has ended")
        if artifact_id not in self._identifiers:
            raise ValueError("Artifact is outside the prepared read identity set")
        record = self._records.get(artifact_id)
        if (
            record is not None
            and record.reservation.retained_until is not None
            and record.reservation.retained_until <= datetime.now(UTC)
        ):
            return None
        return record

    def _read_payload_bytes_for_record(
        self, artifact_id: ArtifactId, record: CloudArtifactPayloadRecord | None, *, max_bytes: int
    ) -> bytes:
        previous = (
            self._verified_payload_owner._verified_payloads.get(artifact_id)
            if self.reuse_verified_payloads
            else None
        )
        if previous is not None and previous[0] == record:
            return super()._read_payload_bytes_for_record(artifact_id, record, max_bytes=max_bytes)
        # Phase metadata revalidation alone cannot stop object two after a
        # revocation during object one. Physical I/O is always a fresh boundary.
        self.check_authority()
        body = super()._read_payload_bytes_for_record(artifact_id, record, max_bytes=max_bytes)
        self.check_authority()
        return body

    def store_payload_immutable(self, *args: Any, **kwargs: Any) -> Any:
        raise ValueError("prepared Artifact read scope cannot publish")

    def store_payloads_immutable(self, *args: Any, **kwargs: Any) -> Any:
        raise ValueError("prepared Artifact read scope cannot publish")
