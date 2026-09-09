"""Immutable package metadata, independent of ZIP parsing and object backends."""

from __future__ import annotations

import json
from typing import Literal, Self
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.artifact_objects import ArtifactObjectExpectation, ArtifactObjectReceipt
from agent_core.domain.extensions import (
    ExtensionDigest,
    ExtensionScope,
    OpaqueExtensionId,
    SkillVersion,
)
from agent_core.domain.identifiers import ArtifactId


def publication_identity(
    deployment_namespace: str, scope: ExtensionScope, name: str, version_label: str,
) -> tuple[str, str, ArtifactId]:
    def identity(domain: str, *coordinates: str) -> str:
        return str(uuid5(NAMESPACE_URL, json.dumps(
            (domain, *coordinates), ensure_ascii=True, separators=(",", ":"),
        )))

    return (
        identity("zebra.skill", name),
        identity("zebra.skill.version", name, version_label),
        ArtifactId(uuid5(NAMESPACE_URL, json.dumps(
            ("zebra.skill.package", deployment_namespace, scope.authority_issuer,
             scope.namespace_id, scope.principal_id, scope.workspace_id, name, version_label),
            ensure_ascii=True, separators=(",", ":"),
        ))),
    )


class SkillPublicationFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(strict=True, min_length=1, max_length=65535)
    size: int = Field(strict=True, ge=0, le=50 * 1024 * 1024)
    sha256: ExtensionDigest


class SkillPublication(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: ExtensionScope
    version: SkillVersion
    name: OpaqueExtensionId = Field(max_length=64)
    description: str = Field(strict=True, min_length=1, max_length=1024)
    version_label: OpaqueExtensionId = Field(max_length=64)
    manifest: tuple[SkillPublicationFile, ...] = Field(min_length=1, max_length=1000)
    expectation: ArtifactObjectExpectation
    state: Literal["publishing", "ready"] = "publishing"
    receipt: ArtifactObjectReceipt | None = None

    @model_validator(mode="after")
    def validate_publication(self) -> Self:
        if self.expectation.size_bytes > 10 * 1024 * 1024:
            raise ValueError("publication exceeds archive package limit")
        skill_id, version_id, artifact_id = publication_identity(
            self.expectation.deployment_namespace, self.scope, self.name, self.version_label,
        )
        if (self.version.skill_id != skill_id or self.version.version_id != version_id
                or self.expectation.artifact_id != artifact_id
                or self.version.artifact_ref != f"artifact://{artifact_id}"):
            raise ValueError("publication identity disagrees with immutable coordinates")
        if (self.state == "ready") != (self.receipt is not None):
            raise ValueError("only ready publications carry receipts")
        if self.receipt is not None and self.receipt.expectation != self.expectation:
            raise ValueError("publication receipt disagrees with expectation")
        paths = tuple(entry.path for entry in self.manifest)
        if paths != tuple(sorted(set(paths))) or "SKILL.md" not in paths:
            raise ValueError("manifest must contain unique sorted files including SKILL.md")
        if sum(entry.size for entry in self.manifest) > 50 * 1024 * 1024:
            raise ValueError("manifest exceeds expanded package limit")
        return self

    def same_candidate(self, other: SkillPublication) -> bool:
        return self.model_dump(exclude={"state", "receipt"}) == other.model_dump(
            exclude={"state", "receipt"},
        )
