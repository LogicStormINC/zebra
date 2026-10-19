"""Bounded Cloud package descriptors; component metadata grants no authority."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from hashlib import sha256
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from agent_core.domain.plugins import PluginEntryKind, PluginManifest


def plugin_package_digest(canonical_manifest: str, files: Iterable[tuple[str, int, str]]) -> str:
    """Full package identity shared by directory validation and immutable pins."""
    value = json.dumps(
        {"manifest": json.loads(canonical_manifest), "files": list(files)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return "sha256:" + sha256(value.encode()).hexdigest()

MAX_PLUGIN_COMPONENTS = 32
PluginComponentId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{2,63}$")]


def normalize_plugin_path(value: str) -> str:
    """Portable relative path shared by descriptors and actual package entries."""
    parts = value.split("/")
    if (
        PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or "\\" in value
        or any(unicodedata.category(char).startswith("C") for char in value)
        or any(char in '<>:"|?*' for char in value)
        or any(
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or PureWindowsPath(part).is_reserved()
            for part in parts
        )
    ):
        raise ValueError("plugin path must be a normalized relative path")
    return unicodedata.normalize("NFC", value)


class PluginSkillComponent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: PluginComponentId
    kind: Literal["skill-bundle"]
    skill_root: str = Field(min_length=1, max_length=1024)

    @field_validator("skill_root")
    @classmethod
    def require_relative_root(cls, value: str) -> str:
        return normalize_plugin_path(value)


class PluginMcpHttpComponent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: PluginComponentId
    kind: Literal["mcp-http"]
    connection_slot: PluginComponentId


PluginPackageComponent = Annotated[
    PluginSkillComponent | PluginMcpHttpComponent, Field(discriminator="kind")
]


class PluginPackageManifest(BaseModel):
    """v0.2 logical components, independent of tenant scope and credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: Literal["0.2"] = "0.2"
    id: PluginComponentId
    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
    publisher: str = Field(min_length=1, max_length=128)
    components: tuple[PluginPackageComponent, ...] = Field(
        min_length=1, max_length=MAX_PLUGIN_COMPONENTS
    )

    @field_validator("publisher")
    @classmethod
    def require_publisher(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("publisher must not be blank")
        return value

    @field_validator("components")
    @classmethod
    def require_unique_components(
        cls, value: tuple[PluginPackageComponent, ...]
    ) -> tuple[PluginPackageComponent, ...]:
        if len({component.id for component in value}) != len(value):
            raise ValueError("duplicate component id")
        roots = [
            component.skill_root
            for component in value
            if isinstance(component, PluginSkillComponent)
        ]
        # ponytail: pairwise checks are bounded by 32 components; use a path
        # trie if a future manifest version lifts that ceiling.
        for index, root in enumerate(roots):
            if any(
                PurePosixPath(root).is_relative_to(other)
                or PurePosixPath(other).is_relative_to(root)
                for other in roots[:index]
            ):
                raise ValueError("overlapping skill roots")
        return value

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @classmethod
    def validate_document(cls, document: object) -> Self:
        if not isinstance(document, dict):
            raise ValueError("plugin manifest must be a JSON object")
        return cls.model_validate(document)


def normalize_plugin_manifest(document: object) -> PluginPackageManifest:
    """Normalize supported v0.1 entries; legacy executable entries stay local."""
    if not isinstance(document, dict):
        raise ValueError("plugin manifest must be a JSON object")
    if document.get("manifest_version", "0.1") != "0.1":
        return PluginPackageManifest.validate_document(document)
    legacy = PluginManifest.validate_document(document)
    entry = legacy.entry
    if entry.kind is PluginEntryKind.SKILL_BUNDLE:
        allowed = {"kind", "skill_root"}
        component: PluginPackageComponent = PluginSkillComponent(
            id=legacy.id, kind="skill-bundle", skill_root=entry.skill_root or ""
        )
    elif entry.kind is PluginEntryKind.MCP_HTTP:
        allowed = {"kind", "url", "bearer_token_env"}
        component = PluginMcpHttpComponent(id=legacy.id, kind="mcp-http", connection_slot=legacy.id)
    else:
        raise ValueError("unsupported Cloud component kind")
    if set(entry.model_dump(exclude_defaults=True)) - allowed:
        raise ValueError("mixed legacy component shape")
    return PluginPackageManifest(
        id=legacy.id,
        version=legacy.version,
        publisher=legacy.publisher or "unpublished",
        components=(component,),
    )
