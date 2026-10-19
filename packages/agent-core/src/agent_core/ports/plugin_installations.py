"""Separate scoped plugin configuration boundary; no component creation or execution."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.extensions import ExtensionScope, OpaqueExtensionId
from agent_core.domain.plugin_installations import (
    PluginDigest,
    PluginInstallation,
    PluginPackagePin,
)
from agent_core.domain.plugin_packages import PluginPackageManifest
from agent_core.ports.extensions import ExtensionPageRequest


class PluginInstallationPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[PluginInstallation, ...] = Field(max_length=100)
    next_cursor: OpaqueExtensionId | None = None


class PluginInstallationStore(Protocol):
    async def get(self, *, scope: ExtensionScope, installation_id: str) -> PluginInstallation: ...

    async def get_current_batch(
        self,
        *,
        scope: ExtensionScope,
        installation_ids: tuple[str, ...],
    ) -> tuple[PluginInstallation, ...]:
        """One bounded fresh lookup; absent, disabled or unready bindings are omitted."""
        ...

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


class PluginPackageCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    package_digest: PluginDigest
    manifest: PluginPackageManifest


class PluginPackageCatalogPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[PluginPackageCatalogEntry, ...] = Field(max_length=10)
    next_cursor: PluginDigest | None = None


class PluginPackagePublisher(Protocol):
    async def list_packages(self, *, page: ExtensionPageRequest) -> PluginPackageCatalogPage:
        """Read approved descriptors without object writes or user component binding."""
        ...

    async def publish(self, *, package_digest: str) -> PluginPackagePin:
        """Resolve an approved digest to trusted, immutable package facts only."""
        ...
