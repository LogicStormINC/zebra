from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.identifiers import SessionId
from agent_core.domain.mcp import normalize_mcp_allowlist
from agent_core.domain.networking import NetworkProfileName
from agent_core.domain.skills import normalize_skill_components
from agent_core.domain.tool_profiles import ToolProfile


class WorkspaceStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkspaceProjection(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: SessionId
    workspace_root: str
    prepared_at: datetime
    updated_at: datetime
    current_sequence: int
    status: WorkspaceStatus
    policy_profile: str | None = None
    tool_profile: ToolProfile = ToolProfile.CODING
    network_profile: NetworkProfileName = NetworkProfileName.NONE
    network_allowlist: tuple[str, ...] = ()
    mcp_allowlist: tuple[str, ...] | None = None
    skill_components: tuple[str, ...] | None = None
    definition_snapshot: AgentDefinitionSnapshot | None = None
    last_attempt_number: int | None = None
    runtime_name: str | None = None
    runtime_engine: str | None = None
    runtime_image: str | None = None
    runtime_spec_digest: str | None = None
    runtime_network_enforcement: str | None = None
    runtime_workspace_writable: bool | None = None
    snapshot_id: str | None = None
    snapshot_path: str | None = None

    @field_validator("workspace_root")
    @classmethod
    def ensure_workspace_root_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("workspace_root must not be blank")
        return stripped

    @field_validator(
        "policy_profile",
        "runtime_name",
        "runtime_engine",
        "runtime_image",
        "runtime_spec_digest",
        "runtime_network_enforcement",
        "snapshot_id",
        "snapshot_path",
    )
    @classmethod
    def ensure_optional_text_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("optional text field must not be blank when provided")
        return stripped

    @field_validator("mcp_allowlist")
    @classmethod
    def ensure_valid_mcp_allowlist(
        cls,
        value: tuple[str, ...] | None,
    ) -> tuple[str, ...] | None:
        return None if value is None else normalize_mcp_allowlist(value)

    @field_validator("skill_components")
    @classmethod
    def ensure_valid_skill_components(
        cls,
        value: tuple[str, ...] | None,
    ) -> tuple[str, ...] | None:
        return None if value is None else normalize_skill_components(value)
