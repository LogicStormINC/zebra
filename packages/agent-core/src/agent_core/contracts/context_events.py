from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from agent_core.domain.context_capsule import ContextCapsule, ContextSourceEventRange


class ContextCompactedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    before_tokens: int
    after_tokens: int
    removed_message_count: int
    retained_message_count: int
    within_budget: bool
    provenance: str
    focus: str | None = Field(default=None, exclude_if=lambda value: value is None)
    recovered_from_capsule_id: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    through_sequence: int | None = Field(default=None, ge=0, exclude_if=lambda value: value is None)
    capsule: ContextCapsule | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @field_serializer("capsule")
    def serialize_capsule(self, value: ContextCapsule | None) -> dict[str, object] | None:
        return value.model_dump(mode="json") if value is not None else None

    @field_validator("attempt_number")
    @classmethod
    def ensure_positive_attempt_number(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("attempt_number must be positive")
        return value

    @field_validator(
        "before_tokens",
        "after_tokens",
        "removed_message_count",
        "retained_message_count",
    )
    @classmethod
    def ensure_non_negative_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("compaction counts must not be negative")
        return value

    @field_validator("provenance", "focus", "recovered_from_capsule_id")
    @classmethod
    def ensure_provenance_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("provenance must not be blank")
        return stripped


class ContextCapsuleCreatedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capsule_id: str
    artifact_id: str
    schema_version: str
    source_hash: str
    source_event_range: ContextSourceEventRange
    previous_capsule_id: str | None = None

    @field_validator(
        "capsule_id",
        "artifact_id",
        "schema_version",
        "source_hash",
        "previous_capsule_id",
    )
    @classmethod
    def ensure_capsule_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("context capsule event fields must not be blank")
        return stripped


class ContextContinuationSelectedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int = Field(gt=0)
    mode: str
    reason: str
    reference_id: str | None = None
    provider: str | None = None
    model_name: str | None = None
    capability_version: str | None = None
    source_hash: str | None = None
    artifact_id: str | None = None
    authority_issuer: str | None = None
    namespace_id: str | None = None
    payload_sha256: str | None = None

    @field_validator(
        "mode",
        "reason",
        "reference_id",
        "provider",
        "model_name",
        "capability_version",
        "source_hash",
        "artifact_id",
        "authority_issuer",
        "namespace_id",
        "payload_sha256",
    )
    @classmethod
    def ensure_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("context continuation fields must not be blank")
        return normalized
