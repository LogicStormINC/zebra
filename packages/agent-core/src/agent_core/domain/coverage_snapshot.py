"""Immutable metadata references; large bodies and manifests live in Artifacts."""

import hashlib
from typing import Literal, Self

from pydantic import Field, model_validator

from agent_core.domain.coverage_contracts import (
    CoverageArtifactRef,
    CoverageCount,
    CoverageDigest,
    CoverageModel,
    CoverageName,
    CoverageRefusalReason,
    CoverageRefusedError,
    CoverageSchemaVersion,
    CoverageTime,
)


class CoveragePart(CoverageModel):
    id: CoverageName
    kind: Literal["canonical_body"] = "canonical_body"
    digest: CoverageDigest
    byte_length: CoverageCount

    def verify_bytes(self, body: bytes) -> None:
        if len(body) != self.byte_length or hashlib.sha256(body).hexdigest() != self.digest:
            raise CoverageRefusedError(CoverageRefusalReason.PART_MISMATCH)


class CoverageRecord(CoverageModel):
    ordinal: CoverageCount
    record_id: CoverageName
    content_digest: CoverageDigest
    parts: tuple[CoveragePart, ...] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def unique_parts(self) -> Self:
        if len({part.id for part in self.parts}) != len(self.parts):
            raise ValueError("part IDs must be unique within a record")
        return self

    @property
    def identity(self) -> tuple[str, str]:
        return self.record_id, self.content_digest

    @property
    def part_keys(self) -> tuple[tuple[str, str, str, str], ...]:
        return tuple((*self.identity, part.id, part.digest) for part in self.parts)


class CoverageSnapshot(CoverageModel):
    schema_version: CoverageSchemaVersion = 1
    state: Literal["sealed"] = "sealed"
    namespace: CoverageName
    host_id: CoverageName
    snapshot_id: CoverageName
    authority_revision: CoverageName
    contract_digest: CoverageDigest
    scope_digest: CoverageDigest
    manifest_digest: CoverageDigest
    record_count: CoverageCount
    manifest_artifact_ref: CoverageArtifactRef
    source_resource_ref: CoverageName | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    as_of: CoverageTime
    expires_at: CoverageTime

    @model_validator(mode="after")
    def validate_seal(self) -> Self:
        if self.expires_at <= self.as_of:
            raise ValueError("snapshot expiry must follow as_of")
        return self


class CoveragePageRequest(CoverageModel):
    namespace: CoverageName
    snapshot_id: CoverageName
    scope_digest: CoverageDigest
    page_size: int = Field(strict=True, ge=1, le=1000)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)


class CoveragePage(CoverageModel):
    namespace: CoverageName
    snapshot_id: CoverageName
    scope_digest: CoverageDigest
    records: tuple[CoverageRecord, ...] = Field(max_length=1000)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def unique_records(self) -> Self:
        if len({record.record_id for record in self.records}) != len(self.records):
            raise ValueError("page contains duplicate record IDs")
        return self

    def validate_for(self, request: CoveragePageRequest) -> None:
        if (
            self.namespace != request.namespace
            or self.snapshot_id != request.snapshot_id
            or self.scope_digest != request.scope_digest
            or len(self.records) > request.page_size
            or (self.next_cursor is not None and self.next_cursor == request.cursor)
        ):
            raise CoverageRefusedError(CoverageRefusalReason.SCOPE_MISMATCH)


class CoveragePartRead(CoverageModel):
    namespace: CoverageName
    snapshot_id: CoverageName
    record_id: CoverageName
    content_digest: CoverageDigest
    part: CoveragePart
    artifact_ref: CoverageArtifactRef
