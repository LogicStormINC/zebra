"""Separate scoped plugin configuration boundary; no component creation or execution."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.extensions import ExtensionScope, OpaqueExtensionId
from agent_core.domain.plugin_installations import PluginInstallation
from agent_core.ports.extensions import ExtensionPageRequest


class PluginInstallationPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[PluginInstallation, ...] = Field(max_length=100)
    next_cursor: OpaqueExtensionId | None = None


class PluginInstallationStore(Protocol):
    async def get(self, *, scope: ExtensionScope, installation_id: str) -> PluginInstallation: ...

    async def get_creation(
        self,
        *,
        scope: ExtensionScope,
        installation_id: str,
    ) -> PluginInstallation: ...

    async def get_revision(
        self,
        *,
        scope: ExtensionScope,
        installation_id: str,
        revision: int,
    ) -> PluginInstallation:
        """Load immutable pinned facts, not the current enablement state."""
        ...

    async def list(
        self,
        *,
        scope: ExtensionScope,
        page: ExtensionPageRequest,
    ) -> PluginInstallationPage: ...

    async def save(
        self,
        *,
        scope: ExtensionScope,
        installation: PluginInstallation,
        expected_revision: int | None,
    ) -> None:
        """Create disabled at revision 1; CAS updates lock and recheck enabled bindings.

        Package/binding changes must remain disabled. Missing scope/revision uses
        ExtensionNotFoundError; stale revisions/bindings use ExtensionRevisionConflictError.
        """
        ...
