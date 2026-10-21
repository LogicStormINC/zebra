"""Explicit v2 Definition contracts; legacy canonical algorithms remain unchanged."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, SerializeAsAny, WrapValidator, model_validator

from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot, BindingPurpose
from agent_core.domain.agent_definitions import (
    AgentDefinitionVersion,
    AgentRelease,
    AgentReleaseStatus,
)
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_core.domain.runtime_bundle_json import json_digest


class BundleDefinitionVersion(AgentDefinitionVersion):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    schema_version: Literal["agent-definition/2"] = "agent-definition/2"
    runtime_assembly: RuntimeAssembly

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        scope = self.runtime_assembly.bundle.manifest.scope
        if (scope.authority_issuer, scope.namespace_id) != (
            self.authority_issuer,
            self.namespace_id,
        ):
            raise ValueError("Bundle scope does not match Definition Version scope")
        expected = canonical_bundle_definition_digest(self)
        if self.definition_digest is not None and self.definition_digest != expected:
            raise ValueError("definition_digest does not match immutable Bundle Version content")
        object.__setattr__(self, "definition_digest", expected)
        return self

    @classmethod
    def from_definition(cls, *args: Any, **kwargs: Any) -> Self:
        raise ValueError("use materialize_version with an explicit RuntimeAssembly")


def canonical_bundle_definition_digest(version: BundleDefinitionVersion) -> str:
    payload = version.model_dump(
        mode="json", exclude={"version_id", "created_at", "definition_digest"}
    )
    return json_digest(payload).removeprefix("sha256:")


class BundleDefinitionSnapshot(AgentDefinitionSnapshot):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
    snapshot_schema_version: Literal["agent-definition-snapshot/2"] = "agent-definition-snapshot/2"
    bound_version: BundleDefinitionVersion

    @model_validator(mode="after")
    def validate_purpose_shape(self) -> Self:
        version = self.bound_version
        for name in AgentDefinitionSnapshot.model_fields:
            if name in AgentDefinitionVersion.model_fields and getattr(self, name) != getattr(
                version, name
            ):
                raise ValueError(f"snapshot {name} differs from embedded Version")
        release_fields = (self.release_id, self.release_revision, self.release_status)
        if self.binding_purpose is BindingPurpose.PRODUCTION:
            if (
                any(field is None for field in release_fields)
                or self.release_status is not AgentReleaseStatus.PUBLISHED
                or self.release_revision is None
                or self.release_revision < 1
            ):
                raise ValueError("production snapshots require a Published Release")
        elif any(field is not None for field in release_fields):
            raise ValueError("eval snapshots must not carry Release fields")
        if self.snapshot_digest != canonical_bundle_snapshot_digest(self):
            raise ValueError("snapshot_digest does not match Bundle snapshot content")
        return self

    @classmethod
    def from_version(cls, *, version: AgentDefinitionVersion, resolved_at: datetime) -> Self:
        checked = parse_definition_version(version)
        if not isinstance(checked, BundleDefinitionVersion):
            raise ValueError("Bundle snapshot requires Bundle Definition Version")
        return cls._from_bound(checked, resolved_at=resolved_at)

    @classmethod
    def from_release(
        cls, *, release: AgentRelease, version: AgentDefinitionVersion, resolved_at: datetime
    ) -> Self:
        checked = parse_definition_version(version)
        if not isinstance(checked, BundleDefinitionVersion):
            raise ValueError("Bundle snapshot requires Bundle Definition Version")
        if (
            release.definition_id,
            release.version_id,
            release.definition_digest,
            release.authority_issuer,
            release.namespace_id,
        ) != (
            checked.definition_id,
            checked.version_id,
            checked.definition_digest,
            checked.authority_issuer,
            checked.namespace_id,
        ):
            raise ValueError("Release does not match embedded Version")
        require_bundle_environment(checked, release.environment)
        return cls._from_bound(checked, resolved_at=resolved_at, release=release)

    @classmethod
    def _from_bound(
        cls,
        version: BundleDefinitionVersion,
        *,
        resolved_at: datetime,
        release: AgentRelease | None = None,
    ) -> Self:
        values = {
            name: getattr(version, name)
            for name in AgentDefinitionSnapshot.model_fields
            if name in AgentDefinitionVersion.model_fields
        }
        values.update(
            snapshot_schema_version="agent-definition-snapshot/2",
            bound_version=version,
            resolved_at=resolved_at,
            binding_purpose=BindingPurpose.EVAL if release is None else BindingPurpose.PRODUCTION,
            release_id=None if release is None else release.release_id,
            release_revision=None if release is None else release.revision,
            release_status=None if release is None else release.status,
        )
        constructed = cls.model_construct(**values)
        values["snapshot_digest"] = canonical_bundle_snapshot_digest(constructed)
        return cls.model_validate(values)


def canonical_bundle_snapshot_digest(snapshot: BundleDefinitionSnapshot) -> str:
    return json_digest(snapshot.model_dump(mode="json", exclude={"snapshot_digest"})).removeprefix(
        "sha256:"
    )


def parse_definition_version(value: object) -> AgentDefinitionVersion:
    payload = value.model_dump() if isinstance(value, AgentDefinitionVersion) else value
    if not isinstance(payload, dict):
        raise ValueError("Definition Version must be an object")
    schema = payload.get("schema_version", "agent-definition/1")
    if schema == "agent-definition/1":
        return AgentDefinitionVersion.model_validate(payload)
    if schema == "agent-definition/2":
        return BundleDefinitionVersion.model_validate(payload)
    raise ValueError("unsupported Definition Version schema")


def parse_definition_snapshot(value: object) -> AgentDefinitionSnapshot:
    payload = value.model_dump() if isinstance(value, AgentDefinitionSnapshot) else value
    if not isinstance(payload, dict):
        raise ValueError("Definition snapshot must be an object")
    schema = payload.get("snapshot_schema_version", "agent-definition-snapshot/1")
    if schema == "agent-definition-snapshot/1":
        return AgentDefinitionSnapshot.model_validate(payload)
    if schema == "agent-definition-snapshot/2":
        return BundleDefinitionSnapshot.model_validate(payload)
    raise ValueError("unsupported Definition snapshot schema")


# The base after-validator hashes v1 content even for subclasses; dispatch validates once.
DefinitionSnapshot = Annotated[
    SerializeAsAny[AgentDefinitionSnapshot],
    WrapValidator(lambda value, handler: parse_definition_snapshot(value)),
]


def snapshot_from_version(
    *, version: AgentDefinitionVersion, resolved_at: datetime
) -> AgentDefinitionSnapshot:
    checked = parse_definition_version(version)
    cls = (
        BundleDefinitionSnapshot
        if isinstance(checked, BundleDefinitionVersion)
        else AgentDefinitionSnapshot
    )
    return cls.from_version(version=checked, resolved_at=resolved_at)


def snapshot_from_release(
    *, release: AgentRelease, version: AgentDefinitionVersion, resolved_at: datetime
) -> AgentDefinitionSnapshot:
    checked = parse_definition_version(version)
    cls = (
        BundleDefinitionSnapshot
        if isinstance(checked, BundleDefinitionVersion)
        else AgentDefinitionSnapshot
    )
    return cls.from_release(version=checked, release=release, resolved_at=resolved_at)


def require_bundle_environment(version: AgentDefinitionVersion, environment: str) -> None:
    checked = parse_definition_version(version)
    if (
        isinstance(checked, BundleDefinitionVersion)
        and checked.runtime_assembly.bundle.manifest.scope.environment != environment
    ):
        raise ValueError("Bundle environment does not match requested environment")
