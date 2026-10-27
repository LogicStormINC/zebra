"""Pinned Cloud package facts; installation never grants execution authority."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.artifact_objects import ArtifactObjectExpectation, ArtifactObjectReceipt
from agent_core.domain.extensions import (
    ExtensionDigest,
    ExtensionRevision,
    ExtensionScope,
    McpConnection,
    OpaqueExtensionId,
    SkillInstallation,
)
from agent_core.domain.plugin_packages import (
    PluginComponentId,
    PluginPackageManifest,
    PluginSkillComponent,
    normalize_plugin_manifest,
    normalize_plugin_path,
    plugin_package_digest,
)
from agent_core.domain.skill_publications import SkillPublicationFile

PluginDigest = Annotated[str, Field(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")]


class PluginPackagePin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: PluginPackageManifest
    canonical_manifest: str = Field(strict=True, min_length=1, max_length=65536)
    manifest_digest: PluginDigest
    package_digest: PluginDigest
    files: tuple[SkillPublicationFile, ...] = Field(default=(), max_length=1000)
    expectation: ArtifactObjectExpectation
    receipt: ArtifactObjectReceipt

    @model_validator(mode="after")
    def validate_pin(self) -> Self:
        if normalize_plugin_manifest(json.loads(self.canonical_manifest)) != self.manifest:
            raise ValueError("original and normalized manifests disagree")
        if self.manifest_digest != "sha256:" + sha256(self.canonical_manifest.encode()).hexdigest():
            raise ValueError("manifest digest disagrees with original manifest")
        if self.package_digest != plugin_package_digest(
            self.canonical_manifest,
            ((file.path, file.size, file.sha256) for file in self.files),
        ):
            raise ValueError("package digest disagrees with manifest and file index")
        if self.receipt.expectation != self.expectation:
            raise ValueError("package receipt disagrees with expectation")
        paths = tuple(file.path for file in self.files)
        if paths != tuple(sorted(set(paths))) or len({path.casefold() for path in paths}) != len(
            paths
        ):
            raise ValueError("package index must contain unique sorted paths")
        if any(normalize_plugin_path(path) != path or path == "plugin.json" for path in paths):
            raise ValueError("package index paths must be normalized content paths")
        if sum(file.size for file in self.files) > 50 * 1024 * 1024:
            raise ValueError("package index exceeds expanded package limit")
        return self

    def skill_files(self, component_id: str) -> tuple[SkillPublicationFile, ...]:
        component = next(item for item in self.manifest.components if item.id == component_id)
        if not isinstance(component, PluginSkillComponent):
            raise ValueError("component is not a Skill bundle")
        root = component.skill_root + "/"
        return tuple(
            file.model_copy(update={"path": file.path.removeprefix(root)})
            for file in self.files
            if file.path.startswith(root)
        )


class PluginSkillBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: PluginComponentId
    kind: Literal["skill-bundle"] = "skill-bundle"
    installation: SkillInstallation


class PluginMcpBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: PluginComponentId
    kind: Literal["mcp-http"] = "mcp-http"
    connection: McpConnection
    catalog_digest: ExtensionDigest


PluginBinding = Annotated[PluginSkillBinding | PluginMcpBinding, Field(discriminator="kind")]


class PluginInstallation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ExtensionScope
    installation_id: OpaqueExtensionId
    revision: ExtensionRevision
    operated_by: OpaqueExtensionId
    operated_at: datetime
    creation_key_digest: ExtensionDigest
    creation_request_digest: ExtensionDigest
    package: PluginPackagePin
    bindings: tuple[PluginBinding, ...] = Field(min_length=1, max_length=32)
    distribution_digest: PluginDigest | None = Field(default=None, exclude_if=lambda v: v is None)
    enabled: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.operated_at.tzinfo is None:
            raise ValueError("operation timestamp must be timezone-aware")
        components = {item.id: item.kind for item in self.package.manifest.components}
        if (
            len({item.component_id for item in self.bindings}) != len(self.bindings)
            or {item.component_id: item.kind for item in self.bindings} != components
        ):
            raise ValueError("bindings must exactly cover package components and kinds")
        for binding in self.bindings:
            record = (
                binding.installation
                if isinstance(binding, PluginSkillBinding)
                else binding.connection
            )
            if record.scope != self.scope:
                raise ValueError("component binding belongs to another scope")
        return self
