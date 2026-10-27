from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.bundle_definition import DefinitionSnapshot
from agent_core.domain.context_inheritance import DelegatedContextSnapshot
from agent_core.domain.coverage_task_admission import (
    CoverageTaskAdmission,
    coverage_admission_input,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.session_history import normalize_history_session_ids
from agent_core.domain.skills import normalize_skill_components
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.turns import InteractionMode


class TaskPreparedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    user_input: str
    coverage_admission: CoverageTaskAdmission | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    workspace_root: str | None = None
    policy_profile: str | None = None
    tool_profile: ToolProfile | None = None
    network_profile: NetworkProfileName | None = None
    network_allowlist: list[str] | None = None
    mcp_allowlist: list[str] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    skill_components: list[str] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    history_session_ids: list[str] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    max_attempts: int | None = None
    max_model_calls: int | None = None
    max_tool_calls: int | None = None
    host_context: HostContextEnvelope | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    definition_snapshot: DefinitionSnapshot | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    delegated_context: DelegatedContextSnapshot | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    interaction_mode: InteractionMode | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    model_profile: str | None = Field(
        default=None,
        max_length=128,
        exclude_if=lambda value: value is None,
    )
    reasoning_effort: str | None = Field(
        default=None,
        max_length=32,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="before")
    @classmethod
    def reconstruct_strict_identity(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("coverage_admission") is not None:
            return {
                **value,
                "coverage_admission": coverage_admission_input(value["coverage_admission"]),
                "host_context": coverage_admission_input(value.get("host_context")),
            }
        return value

    @model_validator(mode="after")
    def require_strict_host(self) -> Self:
        if self.coverage_admission is not None and self.host_context is None:
            raise ValueError("coverage admission requires explicit Host context")
        return self

    @field_validator("title", "user_input")
    @classmethod
    def ensure_required_text_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("workspace_root", "policy_profile", "model_profile", "reasoning_effort")
    @classmethod
    def ensure_optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank when provided")
        return stripped

    @field_validator("mcp_allowlist")
    @classmethod
    def ensure_valid_mcp_allowlist(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(normalize_mcp_allowlist(value))

    @field_validator("skill_components")
    @classmethod
    def ensure_valid_skill_components(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(normalize_skill_components(value))

    @field_validator("history_session_ids")
    @classmethod
    def ensure_valid_history_session_ids(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(normalize_history_session_ids(value))

    @field_validator("max_attempts", "max_model_calls", "max_tool_calls")
    @classmethod
    def ensure_optional_positive_int(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("field must be positive when provided")
        return value
