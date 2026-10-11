"""Exact identity validation, not a claim about model semantic accuracy."""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from agent_core.domain.coverage_contracts import (
    CoverageContract,
    CoverageCount,
    CoverageDigest,
    CoverageModel,
    CoverageName,
    CoverageRefusalReason,
    CoverageRefusedError,
    CoverageSchemaVersion,
    CoverageTime,
    coverage_digest,
)
from agent_core.domain.coverage_snapshot import CoverageRecord, CoverageSnapshot


class CoverageUnitKey(CoverageModel):
    record_id: CoverageName
    content_digest: CoverageDigest
    check_id: CoverageName
    check_version: CoverageName
    definition_digest: CoverageDigest
    kind: Literal["part", "record_merge"]
    part_id: CoverageName | None = None
    part_digest: CoverageDigest | None = None

    @model_validator(mode="after")
    def validate_part_binding(self) -> Self:
        if self.kind == "part":
            if self.part_id is None or self.part_digest is None:
                raise ValueError("part unit requires part ID and digest")
        elif self.part_id is not None or self.part_digest is not None:
            raise ValueError("record merge binds the complete record, not one part")
        return self


class AcceptedCoverageUnit(CoverageModel):
    """Only program/schema/evidence validation or valid review can accept a unit."""

    key: CoverageUnitKey
    result_digest: CoverageDigest
    outcome: Literal["clear", "finding"]


class CoverageValidationEvidence(CoverageModel):
    """Trusted adapter proofs, never fields supplied by the language model."""

    namespace: CoverageName
    host_id: CoverageName
    snapshot_id: CoverageName
    authority_revision: CoverageName
    authority_valid: bool = Field(strict=True)
    artifacts_readable: bool = Field(strict=True)
    upstream_ready: bool = Field(strict=True)
    unresolved_failures: CoverageCount = 0
    unresolved_reviews: CoverageCount = 0
    aggregate_result_set_digest: CoverageDigest


class CoverageVerdict(CoverageModel):
    reasons: tuple[CoverageRefusalReason, ...]
    expected_units: CoverageCount
    accepted_units: CoverageCount

    @property
    def complete(self) -> bool:
        return not self.reasons

    @property
    def processed_ratio(self) -> float | None:
        if not self.expected_units:
            return None
        return self.accepted_units / self.expected_units


class CoverageCertificate(CoverageModel):
    """Persisted validator receipt; schema alone is not publication authority."""

    schema_version: CoverageSchemaVersion = 1
    namespace: CoverageName
    host_id: CoverageName
    snapshot_id: CoverageName
    authority_revision: CoverageName
    contract_revision: int = Field(strict=True, ge=1)
    contract_digest: CoverageDigest
    scope_digest: CoverageDigest
    manifest_digest: CoverageDigest
    enumerated_records: CoverageCount
    read_parts: CoverageCount
    processed_units: CoverageCount
    reviewed_units: CoverageCount
    result_set_digest: CoverageDigest
    aggregate_digest: CoverageDigest
    report_digest: CoverageDigest
    validator_version: CoverageName
    event_watermark: int = Field(strict=True, ge=1)
    created_at: CoverageTime
    expires_at: CoverageTime

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("certificate expiry must follow creation")
        if self.reviewed_units > self.processed_units:
            raise ValueError("reviewed units cannot exceed processed units")
        return self


def manifest_digest(contract: CoverageContract, records: tuple[CoverageRecord, ...]) -> str:
    return coverage_digest(
        {
            "schema": "coverage-manifest/1",
            "scope_digest": contract.scope.digest,
            "count": len(records),
            "item_digests": [
                coverage_digest(record.model_dump(mode="json"))
                for record in sorted(records, key=lambda item: item.ordinal)
            ],
        }
    )


def expected_units(
    contract: CoverageContract, records: tuple[CoverageRecord, ...], *, max_units: int | None = None
) -> tuple[CoverageUnitKey, ...]:
    if max_units is not None:
        if type(max_units) is not int or max_units < 0:
            raise ValueError("invalid coverage unit bound")
        if len(contract.checks) * sum(len(record.parts) + 1 for record in records) > max_units:
            raise CoverageRefusedError(CoverageRefusalReason.BUDGET_EXCEEDED)
    units: list[CoverageUnitKey] = []
    for record in records:
        for check in contract.checks:
            binding = {
                "record_id": record.record_id,
                "content_digest": record.content_digest,
                "check_id": check.id,
                "check_version": check.version,
                "definition_digest": check.definition_digest,
            }
            units.extend(
                CoverageUnitKey(**binding, kind="part", part_id=part.id, part_digest=part.digest)
                for part in record.parts
            )
            units.append(CoverageUnitKey(**binding, kind="record_merge"))
    return tuple(units)


def result_set_digest(results: tuple[AcceptedCoverageUnit, ...]) -> str:
    return coverage_digest(
        {
            "schema": "coverage-results/1",
            "results": sorted(
                (result.model_dump(mode="json") for result in results),
                key=coverage_digest,
            ),
        }
    )


def _same_unique_set(expected: tuple[object, ...], actual: tuple[object, ...]) -> bool:
    return (
        len(set(expected)) == len(expected)
        and len(set(actual)) == len(actual)
        and set(expected) == set(actual)
    )


def validate_coverage(
    *,
    contract: CoverageContract,
    snapshot: CoverageSnapshot,
    manifest: tuple[CoverageRecord, ...],
    enumerated: tuple[tuple[str, str], ...],
    read_parts: tuple[tuple[str, str, str, str], ...],
    accepted: tuple[AcceptedCoverageUnit, ...],
    evidence: CoverageValidationEvidence,
    now: datetime,
) -> CoverageVerdict:
    # ponytail: O(N) reference check; storage must use indexed exact-set joins
    # for large manifests rather than materializing unbounded production inputs.
    reasons: list[CoverageRefusalReason] = []
    if now.utcoffset() is None:
        raise ValueError("validation time must be timezone-aware")
    if (
        snapshot.contract_digest != contract.digest
        or snapshot.scope_digest != contract.scope.digest
    ):
        reasons.append(CoverageRefusalReason.SCOPE_MISMATCH)
    if not snapshot.as_of <= now < snapshot.expires_at:
        reasons.append(CoverageRefusalReason.SNAPSHOT_EXPIRED)
    if (
        snapshot.record_count != len(manifest)
        or {item.ordinal for item in manifest} != set(range(len(manifest)))
        or len({item.record_id for item in manifest}) != len(manifest)
        or snapshot.manifest_digest != manifest_digest(contract, manifest)
    ):
        reasons.append(CoverageRefusalReason.MANIFEST_MISMATCH)
    if not _same_unique_set(tuple(item.identity for item in manifest), enumerated):
        reasons.append(CoverageRefusalReason.ENUMERATION_MISMATCH)
    if not _same_unique_set(tuple(key for item in manifest for key in item.part_keys), read_parts):
        reasons.append(CoverageRefusalReason.PART_MISMATCH)
    expected = expected_units(contract, manifest)
    actual = tuple(result.key for result in accepted)
    if not _same_unique_set(expected, actual):
        reasons.append(CoverageRefusalReason.UNIT_MISMATCH)
    for valid, reason in (
        (
            evidence.authority_valid
            and evidence.namespace == snapshot.namespace
            and evidence.host_id == snapshot.host_id
            and evidence.snapshot_id == snapshot.snapshot_id
            and evidence.authority_revision == snapshot.authority_revision,
            CoverageRefusalReason.AUTHORITY_INVALID,
        ),
        (evidence.artifacts_readable, CoverageRefusalReason.ARTIFACT_UNAVAILABLE),
        (evidence.upstream_ready, CoverageRefusalReason.UPSTREAM_NOT_READY),
        (not evidence.unresolved_failures, CoverageRefusalReason.UNRESOLVED_FAILURE),
        (not evidence.unresolved_reviews, CoverageRefusalReason.UNRESOLVED_REVIEW),
        (
            evidence.aggregate_result_set_digest == result_set_digest(accepted),
            CoverageRefusalReason.AGGREGATE_MISMATCH,
        ),
    ):
        if not valid:
            reasons.append(reason)
    return CoverageVerdict(
        reasons=tuple(reasons),
        expected_units=len(expected),
        accepted_units=len(set(expected) & set(actual)),
    )
