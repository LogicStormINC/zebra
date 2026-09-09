"""Scoped persistence boundary; implementations enforce atomic revision comparison."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.extensions import (
    ExtensionScope,
    McpConnection,
    OpaqueExtensionId,
    SkillInstallation,
)
from agent_core.domain.skill_publications import SkillPublication


class ExtensionPageRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    limit: int = Field(default=50, strict=True, ge=1, le=100)
    cursor: OpaqueExtensionId | None = None


class SkillInstallationPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[SkillInstallation, ...] = Field(max_length=100)
    next_cursor: OpaqueExtensionId | None = None


class McpConnectionPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[McpConnection, ...] = Field(max_length=100)
    next_cursor: OpaqueExtensionId | None = None


class ExtensionNotFoundError(LookupError):
    """No record exists in the supplied exact scope (including cross-scope access)."""


class ExtensionRevisionConflictError(RuntimeError):
    """Create collided, or the expected revision no longer matches."""


class ExtensionSkillConflictError(ExtensionRevisionConflictError):
    """Another enabled installation already owns this Skill in the exact scope."""


class ExtensionSkillAuthorizationError(RuntimeError):
    """A frozen Skill selection is no longer authorized in its exact scope."""


@dataclass(frozen=True, slots=True)
class AuthorizedSkill:
    """One frozen installation paired with its live ready publication."""

    installation: SkillInstallation
    publication: SkillPublication


class SkillAuthorizationPort(Protocol):
    async def authorize_frozen_skills(
        self,
        *,
        scope: ExtensionScope,
        installations: tuple[SkillInstallation, ...],
    ) -> tuple[AuthorizedSkill, ...]:
        """Authorize one bounded frozen selection atomically in exact scope."""
        ...


class ExtensionStore(SkillAuthorizationPort, Protocol):
    """All access requires full scope. No unscoped get/list operations exist.

    save uses expected_revision=None for create (record revision must be 1).
    Updates require a positive expected revision and record revision exactly one
    higher. A missing update raises NotFound; mismatch/create collision raises
    RevisionConflict. Scope disagreement must be rejected before any write.
    """

    async def get_skill_publication(
        self,
        *,
        scope: ExtensionScope,
        skill_id: str,
        version_id: str,
    ) -> SkillPublication:
        """Read publication metadata in the same deployment and exact scope."""
        ...

    async def get_skill_creation(
        self,
        *,
        scope: ExtensionScope,
        installation_id: str,
    ) -> SkillInstallation:
        """Return immutable revision 1 in the exact scope, or raise NotFound."""
        ...

    async def get_skill(
        self,
        *,
        scope: ExtensionScope,
        installation_id: str,
    ) -> SkillInstallation: ...

    async def list_skills(
        self,
        *,
        scope: ExtensionScope,
        page: ExtensionPageRequest,
    ) -> SkillInstallationPage: ...

    async def save_skill(
        self,
        *,
        scope: ExtensionScope,
        installation: SkillInstallation,
        expected_revision: int | None,
    ) -> None: ...

    async def get_mcp(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
    ) -> McpConnection: ...

    async def list_mcp(
        self,
        *,
        scope: ExtensionScope,
        page: ExtensionPageRequest,
    ) -> McpConnectionPage: ...

    async def get_mcp_creation(
        self,
        *,
        scope: ExtensionScope,
        connection_id: str,
    ) -> McpConnection:
        """Return immutable revision 1 in the exact scope, or raise NotFound."""
        ...

    async def save_mcp(
        self,
        *,
        scope: ExtensionScope,
        connection: McpConnection,
        expected_revision: int | None,
    ) -> None: ...
