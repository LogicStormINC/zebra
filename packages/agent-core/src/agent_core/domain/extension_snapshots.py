"""Deterministic, scope-bound extension inputs frozen for one session turn."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.execution_authority_support import digest
from agent_core.domain.extensions import (
    ExtensionDigest,
    ExtensionScope,
    McpAuthState,
    McpConnection,
    OpaqueExtensionId,
    SkillInstallation,
)
from agent_core.domain.task_bindings import TaskBindingSnapshot


class ExtensionPermissions(BaseModel):
    """Explicit permission ceiling. Empty means deny all; there is no wildcard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tools: tuple[OpaqueExtensionId, ...] = Field(default=(), max_length=256)
    resources: tuple[OpaqueExtensionId, ...] = Field(default=(), max_length=256)
    prompts: tuple[OpaqueExtensionId, ...] = Field(default=(), max_length=256)

    @field_validator("tools", "resources", "prompts")
    @classmethod
    def canonical_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("permission identifiers must be unique")
        return tuple(sorted(value))

    def narrow(self, requested: ExtensionPermissions) -> ExtensionPermissions:
        """Intersect a request with this ceiling; callers cannot add capabilities."""
        return ExtensionPermissions(
            tools=tuple(set(self.tools) & set(requested.tools)),
            resources=tuple(set(self.resources) & set(requested.resources)),
            prompts=tuple(set(self.prompts) & set(requested.prompts)),
        )

    def is_subset_of(self, ceiling: ExtensionPermissions) -> bool:
        return self.narrow(ceiling) == self


class McpSnapshotEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connection: McpConnection
    catalog_digest: ExtensionDigest
    permissions: ExtensionPermissions = ExtensionPermissions()

    @model_validator(mode="after")
    def require_available_connection(self) -> Self:
        if not self.connection.enabled or self.connection.auth_state not in (
            McpAuthState.NOT_REQUIRED,
            McpAuthState.READY,
        ):
            raise ValueError("snapshot connection must be enabled and authentication usable")
        return self


class ExtensionSnapshot(BaseModel):
    """Frozen version/configuration/catalog references, not an execution grant.

    Trusted composition narrows permissions against policy and authority first.
    The gateway must still authorize each actual operation at execution time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ExtensionScope
    session_id: OpaqueExtensionId
    turn_id: OpaqueExtensionId
    skills: tuple[SkillInstallation, ...] = Field(default=(), max_length=32)
    mcp: tuple[McpSnapshotEntry, ...] = Field(default=(), max_length=32)

    @field_validator("skills")
    @classmethod
    def canonical_skills(
        cls, value: tuple[SkillInstallation, ...]
    ) -> tuple[SkillInstallation, ...]:
        for ids in (
            [item.installation_id for item in value],
            [item.version.skill_id for item in value],
        ):
            if len(ids) != len(set(ids)):
                raise ValueError("skill identifiers must be unique")
        if any(not item.enabled for item in value):
            raise ValueError("snapshot skills must be enabled")
        return tuple(sorted(value, key=lambda item: item.installation_id))

    @field_validator("mcp")
    @classmethod
    def canonical_mcp(cls, value: tuple[McpSnapshotEntry, ...]) -> tuple[McpSnapshotEntry, ...]:
        ids = [item.connection.connection_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("MCP connection identifiers must be unique")
        return tuple(sorted(value, key=lambda item: item.connection.connection_id))

    @model_validator(mode="after")
    def require_matching_scope(self) -> Self:
        scopes = [item.scope for item in self.skills] + [item.connection.scope for item in self.mcp]
        if any(scope != self.scope for scope in scopes):
            raise ValueError("all snapshot entries must match the exact extension scope")
        return self

    @property
    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))

    def is_subset_of(self, ceiling: ExtensionSnapshot) -> bool:
        """Require identical turn/scope and pinned references, with narrowed permissions."""
        if (self.scope, self.session_id, self.turn_id) != (
            ceiling.scope,
            ceiling.session_id,
            ceiling.turn_id,
        ):
            return False
        if any(skill not in ceiling.skills for skill in self.skills):
            return False
        by_id = {item.connection.connection_id: item for item in ceiling.mcp}
        for item in self.mcp:
            parent = by_id.get(item.connection.connection_id)
            if (
                parent is None
                or item.connection != parent.connection
                or item.catalog_digest != parent.catalog_digest
                or not item.permissions.is_subset_of(parent.permissions)
            ):
                return False
        return True


class ExtensionTaskCeiling(BaseModel):
    """Authoritative root-Task binding and its frozen Skill name ceiling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: OpaqueExtensionId
    binding: TaskBindingSnapshot
    skill_components: tuple[OpaqueExtensionId, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def require_matching_task(self) -> Self:
        if self.binding.task_id != self.task_id:
            raise ValueError("extension Task ceiling disagrees with its binding")
        if len(self.skill_components) != len(set(self.skill_components)):
            raise ValueError("extension Task Skill ceiling must be unique")
        return self
