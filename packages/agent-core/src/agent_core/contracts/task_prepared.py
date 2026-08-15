from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.agent_definitions import AgentDefinition
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.session_history import normalize_history_session_ids
from agent_core.domain.skills import (
    SkillComponentIdentity,
    normalize_skill_component_identities,
    normalize_skill_components,
)
from agent_core.domain.tool_profiles import ToolProfile

_OPTIONAL_LIST = Field(default=None, exclude_if=lambda value: value is None)


class TaskPreparedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    user_input: str
    workspace_root: str | None = None
    policy_profile: str | None = None
    tool_profile: ToolProfile | None = None
    network_profile: NetworkProfileName | None = None
    network_allowlist: list[str] | None = None
    mcp_allowlist: list[str] | None = _OPTIONAL_LIST
    preapproved_readonly_tools: list[str] | None = _OPTIONAL_LIST
    skill_components: list[str] | None = _OPTIONAL_LIST
    skill_component_identities: list[SkillComponentIdentity] | None = _OPTIONAL_LIST
    agent_definition: AgentDefinition | None = _OPTIONAL_LIST
    history_session_ids: list[str] | None = _OPTIONAL_LIST
    max_attempts: int | None = None
    max_model_calls: int | None = None
    max_tool_calls: int | None = None
    plan_required: bool = Field(
        default=False,
        strict=True,
        exclude_if=lambda value: not value,
    )
    model_id: str | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("title", "user_input")
    @classmethod
    def ensure_required_text_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("workspace_root", "policy_profile", "model_id")
    @classmethod
    def ensure_optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank when provided")
        return stripped

    @field_validator("mcp_allowlist", "preapproved_readonly_tools")
    @classmethod
    def ensure_valid_mcp_allowlist(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(normalize_mcp_allowlist(value))

    @field_validator("skill_components")
    @classmethod
    def ensure_valid_skill_components(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(normalize_skill_components(value))

    @field_validator("skill_component_identities")
    @classmethod
    def ensure_valid_skill_component_identities(
        cls,
        value: list[SkillComponentIdentity] | None,
    ) -> list[SkillComponentIdentity] | None:
        return None if value is None else list(normalize_skill_component_identities(value))

    @model_validator(mode="after")
    def ensure_skill_grant_identity_matches_components(self) -> "TaskPreparedPayload":
        if self.skill_component_identities is None:
            return self
        identities = tuple(identity.name for identity in self.skill_component_identities)
        if self.skill_components is not None and tuple(self.skill_components) != identities:
            raise ValueError("skill component identities must match skill_components")
        return self

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
