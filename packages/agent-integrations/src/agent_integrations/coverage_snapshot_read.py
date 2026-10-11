"""Verified bounded body import after fresh Host metadata and manifest validation."""

from typing import TYPE_CHECKING

from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_snapshot import (
    CoveragePart,
    CoveragePartRead,
    CoverageRecord,
    CoverageSnapshot,
)
from agent_core.domain.host_authority import HostContextEnvelope

from agent_integrations.coverage_snapshot_invocation import OperationBudget
from agent_integrations.coverage_snapshot_wire import decode_chunk

if TYPE_CHECKING:
    from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter


def read_part(
    adapter: "HostCoverageSnapshotAdapter",
    snapshot: CoverageSnapshot,
    record: CoverageRecord,
    part: CoveragePart,
    authority: HostContextEnvelope,
    *,
    verified: tuple[CoverageSnapshot, tuple[CoverageRecord, ...]] | None = None,
    budget: OperationBudget | None = None,
) -> CoveragePartRead:
    budget = budget or adapter.host.budget(authority)
    current, rows = verified or adapter._get(snapshot.snapshot_id, authority, budget)
    # ponytail: legacy non-strict snapshots have no local provenance field.
    # Strict MODEL Task admission independently requires an exact non-null ref.
    if (
        snapshot.source_resource_ref not in (None, adapter.host.resource.resource_id)
        or current.model_dump(exclude={"source_resource_ref"})
        != snapshot.model_dump(exclude={"source_resource_ref"})
    ):
        raise CoverageRefusedError(Reason.SCOPE_MISMATCH)
    if record.ordinal >= len(rows) or rows[record.ordinal] != record or part not in record.parts:
        raise CoverageRefusedError(Reason.PART_MISMATCH)
    maximum = adapter._maximum(authority)
    if part.byte_length > maximum:
        raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
    identifier = adapter.body_artifact_id(snapshot, record, part)
    budget.check()
    stored = adapter.artifacts.load(identifier, "coverage_body", maximum, adapter.host.now())
    if stored is None:
        body = bytearray()
        offset = 0
        while True:
            adapter._live(snapshot)
            value = adapter.host.call(
                "read",
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "record_id": record.record_id,
                    "offset": offset,
                    "max_bytes": 32768,
                },
                authority,
                budget,
            )
            chunk, next_offset = decode_chunk(value, snapshot, record, part, offset)
            budget.check()
            if len(body) + len(chunk) > maximum:
                raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
            body.extend(chunk)
            if next_offset is None:
                break
            offset = next_offset
        budget.check()
        payload = bytes(body)
        part.verify_bytes(payload)
        adapter._live(snapshot)
        uri = adapter.artifacts.publish(
            identifier,
            "coverage_body",
            payload,
            maximum,
            lambda: adapter.host.publication_time(
                authority, budget, snapshot.as_of, snapshot.expires_at
            ),
            snapshot.expires_at,
        )
    else:
        uri, payload = stored
        part.verify_bytes(payload)
    budget.check()
    adapter.host.authority_check(authority)
    adapter._live(snapshot)
    return CoveragePartRead(
        namespace=snapshot.namespace,
        snapshot_id=snapshot.snapshot_id,
        record_id=record.record_id,
        content_digest=record.content_digest,
        part=part,
        artifact_ref=uri,
    )
