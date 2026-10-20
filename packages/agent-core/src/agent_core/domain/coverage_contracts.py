"""Host-admitted exhaustive v1 contracts; never inferred from model prose."""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _trimmed(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("identifier must be non-blank and trimmed")
    return value


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp_input(value: object) -> object:
    if not isinstance(value, datetime | str):
        raise ValueError("timestamp requires an explicit datetime or ISO-8601 string")
    return value


CoverageName = Annotated[str, Field(min_length=1, max_length=256), AfterValidator(_trimmed)]
CoverageDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CoverageTime = Annotated[datetime, BeforeValidator(_timestamp_input), AfterValidator(_utc)]
CoverageCount = Annotated[int, Field(strict=True, ge=0)]
CoverageArtifactRef = Annotated[str, Field(min_length=1, max_length=2048), AfterValidator(_trimmed)]


def _version(value: object) -> object:
    if type(value) is not int:
        raise ValueError("schema_version must be an integer")
    return value


CoverageSchemaVersion = Annotated[Literal[1], BeforeValidator(_version)]
CoverageContractVersion = Annotated[Literal[1, 2], BeforeValidator(_version)]


def coverage_digest(payload: object) -> str:
    """Protocol v1: sorted compact JSON, explicit nulls, UTF-8, no NaN."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CoverageModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CoverageRefusalReason(StrEnum):
    UNSUPPORTED = "coverage_unsupported"
    SCOPE_MISMATCH = "scope_mismatch"
    MANIFEST_MISMATCH = "manifest_mismatch"
    ENUMERATION_MISMATCH = "enumeration_mismatch"
    PART_MISMATCH = "part_mismatch"
    UNIT_MISMATCH = "unit_mismatch"
    SNAPSHOT_EXPIRED = "snapshot_expired"
    AUTHORITY_INVALID = "authority_invalid"
    ARTIFACT_UNAVAILABLE = "artifact_unavailable"
    UPSTREAM_NOT_READY = "upstream_not_ready"
    UNRESOLVED_FAILURE = "unresolved_failure"
    UNRESOLVED_REVIEW = "unresolved_review"
    AGGREGATE_MISMATCH = "aggregate_mismatch"
    BUDGET_EXCEEDED = "budget_exceeded"
    CANCELLED = "cancelled"
    FENCE_LOST = "fence_lost"


class CoverageRefusedError(ValueError):
    def __init__(self, reason: CoverageRefusalReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


class CoverageScope(CoverageModel):
    time_field: Literal["visible_at"] = "visible_at"
    timezone: CoverageName
    from_inclusive: CoverageTime
    to_exclusive: CoverageTime
    source_selection: Literal["all_entitled_periods"] = "all_entitled_periods"

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be an IANA timezone") from error
        if self.from_inclusive >= self.to_exclusive:
            raise ValueError("scope requires a nonempty half-open time range")
        return self

    @property
    def digest(self) -> str:
        return coverage_digest(self.model_dump(mode="json"))


class CoverageSelectionScope(CoverageModel):
    """Host-owned opaque selection; Core never interprets business selectors."""

    selection_ref: CoverageName
    selection_digest: CoverageDigest

    @property
    def digest(self) -> str:
        return coverage_digest(self.model_dump(mode="json"))


class CoverageSourceDefinition(CoverageModel):
    protocol: Literal["coverage-source/2"] = "coverage-source/2"
    resource_type: Annotated[str, Field(min_length=1, max_length=128), AfterValidator(_trimmed)]
    read_scope: CoverageName
    create_scope: CoverageName


class CoverageCheck(CoverageModel):
    id: CoverageName
    version: CoverageName
    kind: Literal["program", "model"]
    # Published definition binds schemas, prompt/extractor/model config and review rules.
    definition_digest: CoverageDigest


class CoverageContract(CoverageModel):
    schema_version: CoverageContractVersion = 1
    mode: Literal["exhaustive"] = "exhaustive"
    dataset: CoverageName = "trench.subscribed_events"
    dataset_revision: CoverageName | None = Field(default=None, exclude_if=lambda v: v is None)
    source: CoverageSourceDefinition | None = Field(default=None, exclude_if=lambda v: v is None)
    scope: CoverageScope | CoverageSelectionScope
    content_requirements: tuple[Literal["canonical_body"], ...] = ("canonical_body",)
    checks: tuple[CoverageCheck, ...] = Field(min_length=1, max_length=32)
    cross_record_checks: tuple[CoverageName, ...] = Field(default=(), max_length=0)
    unresolved_policy: Literal["block"] = "block"
    publication_policy: Literal["certified_report_only"] = "certified_report_only"
    contract_revision: int = Field(default=1, strict=True, ge=1)

    @model_validator(mode="before")
    @classmethod
    def require_explicit_v2_dataset(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("schema_version") == 2 and "dataset" not in value:
            raise ValueError("v2 requires explicit dataset")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.schema_version == 1:
            if (
                self.dataset != "trench.subscribed_events"
                or self.dataset_revision is not None
                or self.source is not None
                or not isinstance(self.scope, CoverageScope)
            ):
                raise ValueError("v1 requires its historical dataset and scope")
        elif (
            self.dataset_revision is None
            or self.source is None
            or not isinstance(self.scope, CoverageSelectionScope)
        ):
            raise ValueError("v2 requires dataset_revision, source and opaque selection scope")
        if self.content_requirements != ("canonical_body",):
            raise ValueError("v1 requires exactly canonical_body")
        identities = tuple(check.id for check in self.checks)
        if len(set(identities)) != len(identities):
            raise ValueError("check IDs must be unique")
        return self

    @property
    def digest(self) -> str:
        return coverage_digest(self.model_dump(mode="json"))

    @property
    def source_definition(self) -> CoverageSourceDefinition:
        if self.source is not None:
            return self.source
        from agent_core.domain.coverage_legacy_source import LEGACY_COVERAGE_SOURCE

        return LEGACY_COVERAGE_SOURCE
