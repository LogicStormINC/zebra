from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.context_capsule import ContextSourceEventRange
from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.sessions import SessionStatus

DEFAULT_MAX_HANDOFF_STAGE = 8
HANDOFF_ENVELOPE_VERSION = "1.0"


class HandoffReason(StrEnum):
    USER_PHASE_BOUNDARY = "user_phase_boundary"
    OPERATOR_HANDOFF = "operator_handoff"
    LONG_TERM_MAINTENANCE = "long_term_maintenance"
    CONTEXT_QUALITY_RECOMMENDATION_CONFIRMED = "context_quality_recommendation_confirmed"


class HandoffActorKind(StrEnum):
    DIRECT_USER = "direct_user"
    OPERATOR = "operator"
    AUTOMATION = "automation"


class HandoffOperationStatus(StrEnum):
    PREPARING = "preparing"
    COMMITTED = "committed"
    ABORTED = "aborted"


class HandoffSideEffectClass(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT_EFFECT = "idempotent_effect"
    NON_IDEMPOTENT_EFFECT = "non_idempotent_effect"


class SessionLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: SessionId
    root_session_id: SessionId
    parent_session_id: SessionId | None = None
    inbound_handoff_id: HandoffId | None = None
    stage_index: int = Field(ge=0, le=DEFAULT_MAX_HANDOFF_STAGE)

    @model_validator(mode="after")
    def validate_shape(self) -> SessionLineage:
        is_root = self.parent_session_id is None and self.inbound_handoff_id is None
        if is_root:
            if self.root_session_id != self.session_id or self.stage_index != 0:
                raise ValueError("root lineage must reference itself at stage zero")
            return self
        if self.parent_session_id is None or self.inbound_handoff_id is None:
            raise ValueError("child lineage requires parent and inbound handoff")
        if self.session_id in {self.root_session_id, self.parent_session_id}:
            raise ValueError("child lineage identities must be distinct")
        if self.stage_index == 0:
            raise ValueError("child lineage stage must be positive")
        return self


class WorkspaceBindingRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    repo_id: str | None = None
    revision_hash: str
    commit_sha: str | None = None
    runtime_snapshot_id: str | None = None

    @field_validator("workspace_id", "revision_hash")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("workspace revision fields must not be blank")
        return value

    @field_validator("repo_id", "commit_sha", "runtime_snapshot_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("workspace revision fields must not be blank when provided")
        return value


class EffectIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    authority_scope_hash: str
    tool_name: str
    operation_kind: str
    target_hash: str
    canonical_effect_hash: str
    external_operation_id_hash: str | None = None

    @field_validator(
        "authority_scope_hash",
        "tool_name",
        "operation_kind",
        "target_hash",
        "canonical_effect_hash",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("effect identity fields must not be blank")
        return value

    @field_validator("external_operation_id_hash")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("external operation hash must not be blank when provided")
        return value

    def ledger_key(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


class CompletedToolEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_call_id: str
    tool_name: str
    terminal_event_sequence: int = Field(ge=0)
    terminal_status: str
    side_effect_class: HandoffSideEffectClass
    result_artifact_ref: str | None = None
    effect_identity: EffectIdentity | None = None

    @field_validator("tool_call_id", "tool_name", "terminal_status")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("completed tool evidence fields must not be blank")
        return value

    @model_validator(mode="after")
    def require_effect_identity(self) -> CompletedToolEvidence:
        if self.side_effect_class is not HandoffSideEffectClass.READ_ONLY:
            if self.effect_identity is None:
                raise ValueError("effectful tool evidence requires an effect identity")
        elif self.effect_identity is not None:
            raise ValueError("read-only tool evidence must not carry an effect identity")
        return self


class SessionHandoffEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    handoff_id: HandoffId
    version: str = HANDOFF_ENVELOPE_VERSION
    source_session_id: SessionId
    target_session_id: SessionId
    root_session_id: SessionId
    source_stage_index: int = Field(ge=0, lt=DEFAULT_MAX_HANDOFF_STAGE)
    target_stage_index: int = Field(gt=0, le=DEFAULT_MAX_HANDOFF_STAGE)
    reason: HandoffReason
    focus: str | None = None
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    protected_user_constraints: tuple[str, ...] = ()
    decisions_and_rationale: tuple[str, ...] = ()
    completed_work: tuple[str, ...] = ()
    pending_work: tuple[str, ...] = ()
    immediate_next: str
    touched_files: tuple[str, ...] = ()
    validation_results: tuple[str, ...] = ()
    known_failures: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    source_context_capsule_id: str | None = None
    source_event_range: ContextSourceEventRange
    source_event_hash: str
    workspace_revision: WorkspaceBindingRevision
    completed_tool_evidence: tuple[CompletedToolEvidence, ...] = ()
    known_omissions: tuple[str, ...] = ()
    created_at: datetime
    checksum: str

    @field_validator("version", "objective", "immediate_next", "source_event_hash")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("handoff envelope fields must not be blank")
        return value

    @field_validator("checksum")
    @classmethod
    def require_checksum(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("handoff checksum must be a sha256 hex digest")
        return value

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("handoff created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_stage_and_identity(self) -> SessionHandoffEnvelope:
        if self.target_stage_index != self.source_stage_index + 1:
            raise ValueError("handoff target stage must follow source stage")
        if len({self.source_session_id, self.target_session_id}) != 2:
            raise ValueError("handoff source and target must be distinct")
        if self.source_stage_index == 0 and self.root_session_id != self.source_session_id:
            raise ValueError("stage-zero handoff source must be the root session")
        return self

    def expected_checksum(self) -> str:
        payload = self.model_dump(mode="json", exclude={"checksum"})
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


class SessionHandoffValidationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_status: SessionStatus
    expected_source_session_id: SessionId
    expected_target_session_id: SessionId
    expected_root_session_id: SessionId
    expected_source_stage_index: int = Field(ge=0)
    expected_source_event_range: ContextSourceEventRange
    expected_source_event_hash: str
    expected_workspace_revision: WorkspaceBindingRevision
    protected_user_constraints: frozenset[str] = frozenset()
    readable_artifact_refs: frozenset[str] = frozenset()
    source_authority: frozenset[str] = frozenset()
    target_authority: frozenset[str] = frozenset()
    terminal_effect_ledger_keys: frozenset[str] = frozenset()
    effective_depth_limit: int = Field(default=DEFAULT_MAX_HANDOFF_STAGE, ge=1)
    parent_has_successor: bool = False
    has_active_lease: bool = False
    has_pending_tool: bool = False
    has_pending_approval: bool = False
    has_pending_clarification: bool = False
    has_uncertain_effect: bool = False


class SessionHandoffValidationError(ValueError):
    def __init__(self, codes: tuple[str, ...]) -> None:
        self.codes = codes
        super().__init__("; ".join(codes))


def validate_session_handoff(
    envelope: SessionHandoffEnvelope,
    context: SessionHandoffValidationContext,
) -> None:
    failures: list[str] = []
    if context.source_status not in {SessionStatus.COMPLETED, SessionStatus.SUSPENDED}:
        failures.append("handoff_source_status_rejected")
    if (
        envelope.source_session_id != context.expected_source_session_id
        or envelope.target_session_id != context.expected_target_session_id
        or envelope.root_session_id != context.expected_root_session_id
        or envelope.source_stage_index != context.expected_source_stage_index
    ):
        failures.append("handoff_lineage_mismatch")
    if envelope.source_event_range != context.expected_source_event_range:
        failures.append("handoff_source_range_mismatch")
    if envelope.source_event_hash != context.expected_source_event_hash:
        failures.append("handoff_source_hash_mismatch")
    if envelope.workspace_revision != context.expected_workspace_revision:
        failures.append("handoff_workspace_revision_mismatch")
    if envelope.checksum != envelope.expected_checksum():
        failures.append("handoff_checksum_mismatch")
    if not context.protected_user_constraints.issubset(envelope.protected_user_constraints):
        failures.append("handoff_protected_constraints_omitted")
    if not set(envelope.artifact_refs).issubset(context.readable_artifact_refs):
        failures.append("handoff_artifact_unreadable")
    if not context.target_authority.issubset(context.source_authority):
        failures.append("handoff_authority_widened")
    if envelope.target_stage_index > context.effective_depth_limit:
        failures.append("handoff_depth_exceeded")
    if context.parent_has_successor:
        failures.append("handoff_successor_conflict")
    if any(
        (
            context.has_active_lease,
            context.has_pending_tool,
            context.has_pending_approval,
            context.has_pending_clarification,
            context.has_uncertain_effect,
        )
    ):
        failures.append("handoff_source_not_quiescent")
    required_effects = {
        evidence.effect_identity.ledger_key()
        for evidence in envelope.completed_tool_evidence
        if evidence.effect_identity is not None
    }
    if not required_effects.issubset(context.terminal_effect_ledger_keys):
        failures.append("handoff_effect_evidence_unverified")
    if failures:
        raise SessionHandoffValidationError(tuple(failures))


def _canonical_json(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
