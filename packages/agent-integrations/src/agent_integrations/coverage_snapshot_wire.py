"""Strict normalization of Trench coverage v1, before projecting core metadata."""

import base64
import binascii
from typing import Literal

from agent_core.domain.coverage_contracts import (
    CoverageContract,
    CoverageContractVersion,
    CoverageCount,
    CoverageDigest,
    CoverageModel,
    CoverageName,
    CoverageRefusalReason,
    CoverageRefusedError,
    CoverageSchemaVersion,
    CoverageScope,
    CoverageSelectionScope,
    CoverageTime,
    coverage_digest,
)
from agent_core.domain.coverage_snapshot import (
    CoveragePage,
    CoveragePart,
    CoverageRecord,
    CoverageSnapshot,
)
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from pydantic import Field, ValidationError, field_validator


class Descriptor(CoverageModel):
    schema_version: CoverageSchemaVersion
    state: Literal["sealed"]
    namespace: CoverageName
    host_id: CoverageName
    snapshot_id: CoverageName
    authority_revision: CoverageDigest
    contract_digest: CoverageDigest
    scope_digest: CoverageDigest
    manifest_digest: CoverageDigest
    record_count: CoverageCount
    as_of: CoverageTime
    expires_at: CoverageTime


class Provenance(CoverageModel):
    dataset: Literal["trench.subscribed_events"]
    history_ref: CoverageName
    workspace_ref: CoverageName
    period_count: CoverageCount
    periods_digest: CoverageDigest


class SnapshotWire(CoverageModel):
    status: Literal["ready"]
    snapshot: Descriptor
    sealed_at: CoverageTime
    content_capabilities: tuple[Literal["canonical_body"], ...]
    scope: CoverageScope
    provenance: Provenance

    @field_validator("scope", mode="before")
    @classmethod
    def full_scope(cls, value: object) -> object:
        if not isinstance(value, dict) or set(value) != set(CoverageScope.model_fields):
            raise ValueError("scope must contain every v1 field")
        return value


class SourceProvenance(CoverageModel):
    dataset: CoverageName
    dataset_revision: CoverageName
    resource_ref: HostResourceRef
    workspace_ref: CoverageName
    authority_revision: CoverageDigest


class SnapshotWireV2(CoverageModel):
    schema_version: CoverageContractVersion
    status: Literal["ready"]
    snapshot: Descriptor
    sealed_at: CoverageTime
    content_capabilities: tuple[Literal["canonical_body"], ...]
    scope: CoverageSelectionScope
    provenance: SourceProvenance

    @field_validator("schema_version")
    @classmethod
    def require_v2(cls, value: int) -> int:
        if value != 2:
            raise ValueError("v2 wire requires schema_version 2")
        return value


def parse_snapshot_wire(
    value: object, contract: CoverageContract | None = None
) -> SnapshotWire | SnapshotWireV2:
    if contract is not None and contract.schema_version == 2:
        return parse(SnapshotWireV2, value, CoverageRefusalReason.SCOPE_MISMATCH)
    return parse(SnapshotWire, value, CoverageRefusalReason.SCOPE_MISMATCH)


def validate_snapshot_provenance(
    wire: SnapshotWire | SnapshotWireV2,
    *,
    contract: CoverageContract | None,
    authority: HostContextEnvelope,
    source_ref: HostResourceRef,
) -> None:
    snapshot = wire.snapshot
    mismatch = (
        snapshot.namespace != authority.namespace_id
        or snapshot.host_id != authority.host_app_id
        or wire.provenance.workspace_ref != authority.workspace_ref
        or wire.content_capabilities != ("canonical_body",)
        or wire.scope.digest != snapshot.scope_digest
        or not snapshot.as_of <= wire.sealed_at < snapshot.expires_at
    )
    if isinstance(wire, SnapshotWireV2):
        mismatch |= (
            contract is None
            or contract.schema_version != 2
            or wire.provenance.resource_ref != source_ref
            or wire.provenance.authority_revision != snapshot.authority_revision
            or (
                contract is not None
                and (
                    wire.provenance.dataset != contract.dataset
                    or wire.provenance.dataset_revision != contract.dataset_revision
                    or source_ref.resource_type != contract.source_definition.resource_type
                )
            )
        )
    else:
        mismatch |= (
            (contract is not None and contract.schema_version != 1)
            or wire.provenance.history_ref != source_ref.resource_id
            or wire.provenance.periods_digest != snapshot.authority_revision
        )
    if contract is not None:
        mismatch |= wire.scope != contract.scope or snapshot.contract_digest != contract.digest
    if mismatch:
        raise CoverageRefusedError(CoverageRefusalReason.SCOPE_MISMATCH)


class PageWire(CoveragePage):
    status: Literal["ready"]
    page_digest: CoverageDigest
    provenance: dict[str, dict[str, object]]
    next_cursor: str | None = Field(min_length=1, max_length=4096)

    @field_validator("records", mode="before")
    @classmethod
    def full_records(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("records must be an array")
        for row in value:
            if not isinstance(row, dict) or set(row) != set(CoverageRecord.model_fields):
                raise ValueError("record must contain every v1 field")
            parts = row["parts"]
            if (
                not isinstance(parts, list)
                or len(parts) != 1
                or not isinstance(parts[0], dict)
                or set(parts[0]) != set(CoveragePart.model_fields)
            ):
                raise ValueError("canonical part must contain every v1 field")
        return value


class ReadWire(CoverageModel):
    status: Literal["ready"]
    namespace: CoverageName
    snapshot_id: CoverageName
    record_id: CoverageName
    content_digest: CoverageDigest
    data_base64: str = Field(max_length=43692)
    offset: CoverageCount
    byte_length: CoverageCount
    digest: CoverageDigest
    next_offset: CoverageCount | None


def parse[T: CoverageModel](model: type[T], value: object, reason: CoverageRefusalReason) -> T:
    try:
        return model.model_validate(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise CoverageRefusedError(reason) from exc


def host_manifest_digest(scope_digest: str, records: tuple[CoverageRecord, ...]) -> str:
    return coverage_digest(
        {
            "schema": "coverage-manifest/1",
            "scope_digest": scope_digest,
            "count": len(records),
            "item_digests": [coverage_digest(record.model_dump(mode="json")) for record in records],
        }
    )


def verify_manifest(
    snapshot: Descriptor | CoverageSnapshot, records: tuple[CoverageRecord, ...]
) -> None:
    if (
        len(records) != snapshot.record_count
        or any(record.ordinal != i for i, record in enumerate(records))
        or len({record.record_id for record in records}) != len(records)
        or any(
            len(record.parts) != 1 or record.parts[0].id != "canonical_body" for record in records
        )
        or host_manifest_digest(snapshot.scope_digest, records) != snapshot.manifest_digest
    ):
        raise CoverageRefusedError(CoverageRefusalReason.MANIFEST_MISMATCH)


def normalize_page(value: dict[str, object]) -> CoveragePage:
    # Hash the entire wire response, including provenance and status, before projection.
    if value.get("page_digest") != coverage_digest(
        {k: v for k, v in value.items() if k != "page_digest"}
    ):
        raise CoverageRefusedError(CoverageRefusalReason.MANIFEST_MISMATCH)
    wire = parse(PageWire, value, CoverageRefusalReason.MANIFEST_MISMATCH)
    if set(wire.provenance) != {record.record_id for record in wire.records}:
        raise CoverageRefusedError(CoverageRefusalReason.MANIFEST_MISMATCH)
    return CoveragePage.model_validate(
        wire.model_dump(exclude={"status", "provenance", "page_digest"})
    )


def decode_chunk(
    value: dict[str, object],
    snapshot: CoverageSnapshot,
    record: CoverageRecord,
    part: CoveragePart,
    offset: int,
) -> tuple[bytes, int | None]:
    wire = parse(ReadWire, value, CoverageRefusalReason.PART_MISMATCH)
    if (
        wire.namespace != snapshot.namespace
        or wire.snapshot_id != snapshot.snapshot_id
        or wire.record_id != record.record_id
        or wire.content_digest != record.content_digest
        or wire.digest != part.digest
        or wire.byte_length != part.byte_length
        or wire.offset != offset
    ):
        raise CoverageRefusedError(CoverageRefusalReason.PART_MISMATCH)
    try:
        chunk = base64.b64decode(wire.data_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CoverageRefusedError(CoverageRefusalReason.PART_MISMATCH) from exc
    end = offset + len(chunk)
    if (
        base64.b64encode(chunk).decode() != wire.data_base64
        or len(chunk) > 32768
        or end > part.byte_length
        or (wire.next_offset is None and end != part.byte_length)
        or (
            wire.next_offset is not None
            and (not chunk or wire.next_offset != end or end >= part.byte_length)
        )
    ):
        raise CoverageRefusedError(CoverageRefusalReason.PART_MISMATCH)
    return chunk, wire.next_offset
