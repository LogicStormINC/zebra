from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TRAILING_PUNCT = "\"'),;>.]}"


def _normalize_ref(value: str) -> str:
    """Strip trailing punctuation that may cling to artifact/event references."""
    return value.strip().rstrip(_TRAILING_PUNCT)


class ContextCapsuleGenerator(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_ASSISTED = "model-assisted"
    PROVIDER_NATIVE_IMPORT = "provider-native-import"


class ContextSourceEventRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_sequence: int = Field(ge=0)
    end_sequence: int = Field(ge=0)

    @model_validator(mode="after")
    def ensure_ordered(self) -> "ContextSourceEventRange":
        if self.end_sequence < self.start_sequence:
            raise ValueError("context capsule source event range must be ordered")
        return self


class ContextCapsuleValidationContext(BaseModel):
    """External facts required before a candidate may become active."""

    model_config = ConfigDict(frozen=True)

    expected_source_hash: str
    expected_source_event_range: ContextSourceEventRange
    unresolved_tool_call_ids: frozenset[str] = frozenset()
    protected_user_constraints: frozenset[str] = frozenset()
    approval_and_policy_state: frozenset[str] = frozenset()
    readable_artifact_refs: frozenset[str] = frozenset()


class ContextCapsuleValidationError(ValueError):
    """Raised when a capsule would lose or misrepresent durable task state."""


class PendingToolState(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ContextCapsule(BaseModel):
    model_config = ConfigDict(frozen=True)

    capsule_id: str
    version: str = "1.0"
    objective: str
    scope: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    protected_user_constraints: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    decisions_and_rationale: tuple[str, ...] = ()
    plan: tuple[str, ...] = ()
    touched_files: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    pending_tools: tuple[PendingToolState, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    approvals_and_policy_state: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    recent_exact_tail_refs: tuple[str, ...] = ()
    immediate_next: str
    source_event_range: ContextSourceEventRange | None = None
    source_hash: str
    profile: str = "zebra-deterministic-v1"
    model_profile: str | None = None
    generator: ContextCapsuleGenerator = ContextCapsuleGenerator.DETERMINISTIC
    confidence: float = Field(ge=0.0, le=1.0)
    known_omissions: tuple[str, ...] = ()
    created_at: datetime

    @property
    def referenced_artifact_refs(self) -> tuple[str, ...]:
        """Union of artifact_refs and recent_exact_tail_refs, de-duplicated and sorted."""
        return tuple(sorted(set(self.artifact_refs) | set(self.recent_exact_tail_refs)))

    @field_validator(
        "capsule_id",
        "version",
        "objective",
        "immediate_next",
        "source_hash",
        "profile",
    )
    @classmethod
    def ensure_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("context capsule fields must not be blank")
        return stripped

    @field_validator("created_at")
    @classmethod
    def ensure_created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("context capsule created_at must be timezone-aware")
        return value

    @field_validator("model_profile")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("context capsule model_profile must not be blank")
        return stripped

    @field_validator("artifact_refs", "recent_exact_tail_refs")
    @classmethod
    def normalize_artifact_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_ref(ref) for ref in value if _normalize_ref(ref))
        return normalized


def validate_context_capsule(
    capsule: ContextCapsule,
    context: ContextCapsuleValidationContext,
) -> None:
    """Validate facts that cannot be checked by the schema alone.

    The caller supplies facts from the durable event/artifact stores.  Keeping
    those reads outside the domain model makes this check deterministic and
    keeps agent-core free of storage dependencies.
    """

    failures: list[str] = []
    if capsule.source_hash != context.expected_source_hash:
        failures.append("source hash does not match the durable event projection")
    if capsule.source_event_range != context.expected_source_event_range:
        failures.append("source event range does not match the durable projection")

    pending_ids = {tool.call_id for tool in capsule.pending_tools}
    if pending_ids != set(context.unresolved_tool_call_ids):
        failures.append("pending tool calls are incomplete or stale")
    if not context.protected_user_constraints.issubset(capsule.protected_user_constraints):
        failures.append("protected user constraints were omitted")
    if not context.approval_and_policy_state.issubset(capsule.approvals_and_policy_state):
        failures.append("approval or policy state was omitted")
    referenced_artifacts = set(capsule.artifact_refs) | set(capsule.recent_exact_tail_refs)
    unreadable = referenced_artifacts - set(context.readable_artifact_refs)
    if unreadable:
        failures.append("artifact references are not readable: " + ", ".join(sorted(unreadable)))

    if failures:
        raise ContextCapsuleValidationError("; ".join(failures))
