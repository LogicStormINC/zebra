from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.session_handoff import HandoffActorKind, HandoffReason


class UserMessageReceivedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    source: str | None = Field(default=None, exclude_if=lambda value: value is None)
    handoff_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    principal_identity_hash: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    actor_kind: HandoffActorKind | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    trust: HandoffActorKind | None = Field(default=None, exclude_if=lambda value: value is None)
    turn_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    turn_index: int | None = Field(
        default=None, ge=0, exclude_if=lambda value: value is None
    )
    origin: str | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("content")
    @classmethod
    def ensure_content_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value

    @field_validator("origin")
    @classmethod
    def constrain_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in ("human", "session_handoff"):
            raise ValueError("user-message origin must be human or session_handoff")
        return value

    @model_validator(mode="after")
    def validate_handoff_provenance(self) -> "UserMessageReceivedPayload":
        provenance = (
            self.source,
            self.handoff_id,
            self.principal_identity_hash,
            self.actor_kind,
            self.trust,
        )
        if all(value is None for value in provenance):
            return self
        if any(value is None for value in provenance):
            raise ValueError("handoff user-message provenance must be complete")
        if self.source != "session_handoff":
            raise ValueError("handoff user-message source must be session_handoff")
        if self.actor_kind is not self.trust:
            raise ValueError("handoff actor kind and trust must agree")
        return self

    @model_validator(mode="after")
    def validate_turn_provenance(self) -> "UserMessageReceivedPayload":
        if self.turn_id is None and self.turn_index is None:
            return self
        if self.turn_id is None or self.turn_index is None:
            raise ValueError("turn identity must carry both turn_id and turn_index")
        if not self.turn_id.strip():
            raise ValueError("turn_id must not be blank")
        return self


class SessionHandoffCommittedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_id: str
    target_session_id: str
    reason: HandoffReason
    target_stage_index: int = Field(gt=0)
    source_event_range: ContextSourceEventRange
    source_event_hash: str
    artifact_id: str
    checksum: str
    idempotency_key_hash: str

    @field_validator(
        "handoff_id",
        "target_session_id",
        "source_event_hash",
        "artifact_id",
        "checksum",
        "idempotency_key_hash",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("handoff committed fields must not be blank")
        return value


class SessionHandoffReceivedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_session_id: str
    root_session_id: str
    handoff_id: str
    stage_index: int = Field(gt=0)
    artifact_id: str
    checksum: str

    @field_validator(
        "parent_session_id",
        "root_session_id",
        "handoff_id",
        "artifact_id",
        "checksum",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("handoff received fields must not be blank")
        return value


class SessionHandoffWorkspaceDriftDetectedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_id: str
    expected_revision_hash: str
    actual_revision_hash: str

    @field_validator("handoff_id", "expected_revision_hash", "actual_revision_hash")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("handoff workspace drift fields must not be blank")
        return value

    @model_validator(mode="after")
    def require_drift(self) -> "SessionHandoffWorkspaceDriftDetectedPayload":
        if self.expected_revision_hash == self.actual_revision_hash:
            raise ValueError("workspace drift event requires different revisions")
        return self
