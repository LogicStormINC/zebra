"""Bounded, secret-free package provenance and explicit component selection."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.extensions import ExtensionRevision, OpaqueExtensionId
from agent_core.domain.plugin_installations import (
    PluginDigest,
    PluginInstallation,
    PluginSkillBinding,
)
from agent_core.domain.plugin_packages import PluginComponentId


class PluginRevisionSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    installation_id: OpaqueExtensionId
    revision: ExtensionRevision


class ExtensionSelection(BaseModel):
    """Omitted request retains legacy selection; an explicit empty value selects nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    plugins: tuple[PluginRevisionSelection, ...] = Field(default=(), max_length=32)
    skills: tuple[OpaqueExtensionId, ...] = Field(default=(), max_length=32)
    mcp: tuple[OpaqueExtensionId, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def unique(self) -> Self:
        for ids in (self.skills, self.mcp, tuple(p.installation_id for p in self.plugins)):
            if len(ids) != len(set(ids)):
                raise ValueError("extension selections must be unique")
        object.__setattr__(self, "skills", tuple(sorted(self.skills)))
        object.__setattr__(self, "mcp", tuple(sorted(self.mcp)))
        object.__setattr__(
            self, "plugins", tuple(sorted(self.plugins, key=lambda p: p.installation_id))
        )
        return self


class PluginComponentSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    component_id: PluginComponentId
    kind: Literal["skill-bundle", "mcp-http"]
    target_id: OpaqueExtensionId


class PluginSnapshot(PluginRevisionSelection):
    distribution_digest: PluginDigest | None = Field(default=None, exclude_if=lambda v: v is None)
    package_id: PluginComponentId
    package_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    manifest_digest: PluginDigest
    package_digest: PluginDigest
    components: tuple[PluginComponentSource, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_components(self) -> Self:
        if len({item.component_id for item in self.components}) != len(self.components):
            raise ValueError("plugin component sources must be unique")
        return self

    @classmethod
    def from_installation(cls, record: PluginInstallation) -> Self:
        return cls(
            installation_id=record.installation_id,
            revision=record.revision,
            distribution_digest=record.distribution_digest,
            package_id=record.package.manifest.id,
            package_version=record.package.manifest.version,
            manifest_digest=record.package.manifest_digest,
            package_digest=record.package.package_digest,
            components=tuple(
                sorted(
                    (
                        PluginComponentSource(
                            component_id=item.component_id,
                            kind=item.kind,
                            target_id=(
                                item.installation.installation_id
                                if isinstance(item, PluginSkillBinding)
                                else item.connection.connection_id
                            ),
                        )
                        for item in record.bindings
                    ),
                    key=lambda item: item.component_id,
                )
            ),
        )
