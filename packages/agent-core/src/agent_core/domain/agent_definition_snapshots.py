"""Immutable Task-level Definition snapshot carried by TASK_PREPARED (ADR-016 §6)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.agent_definitions import (
    AgentDefinitionScope,
    AgentDefinitionVersion,
    AgentRelease,
    AgentReleaseStatus,
    canonical_agent_definition_digest,
)
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
    AgentReleaseId,
)

MAX_SNAPSHOT_REFERENCE_LENGTH = 512
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class BindingPurpose(StrEnum):
    PRODUCTION = "production"
    EVAL = "eval"


class AgentDefinitionSnapshot(BaseModel):
    """One resolved Definition Version bound to a Task; never mutable draft state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_schema_version: str = Field(default="agent-definition-snapshot/1", max_length=64)
    definition_id: AgentDefinitionId
    version_id: AgentDefinitionVersionId
    definition_digest: str
    authority_issuer: str = Field(min_length=1, max_length=2_048)
    namespace_id: str = Field(min_length=1, max_length=255)
    binding_purpose: BindingPurpose
    release_id: AgentReleaseId | None = None
    release_revision: int | None = None
    release_status: AgentReleaseStatus | None = None
    model_policy_ref: str = Field(max_length=MAX_SNAPSHOT_REFERENCE_LENGTH)
    tool_profile_ref: str = Field(max_length=MAX_SNAPSHOT_REFERENCE_LENGTH)
    skill_snapshot_digest: str
    memory_policy_ref: str = Field(max_length=MAX_SNAPSHOT_REFERENCE_LENGTH)
    security_policy_ref: str = Field(max_length=MAX_SNAPSHOT_REFERENCE_LENGTH)
    evaluation_profile_ref: str = Field(max_length=MAX_SNAPSHOT_REFERENCE_LENGTH)
    runtime_profile_ref: str = Field(max_length=MAX_SNAPSHOT_REFERENCE_LENGTH)
    resolved_at: datetime
    snapshot_digest: str

    @field_validator("authority_issuer", "namespace_id")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("definition_digest", "skill_snapshot_digest", "snapshot_digest")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SHA256_PATTERN.fullmatch(value):
            raise ValueError("digests must be lowercase sha256 hexadecimal strings")
        return value

    @field_validator("resolved_at")
    @classmethod
    def require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("resolved_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_purpose_shape(self) -> Self:
        release_fields = (self.release_id, self.release_revision, self.release_status)
        if self.binding_purpose is BindingPurpose.PRODUCTION:
            if any(field is None for field in release_fields):
                raise ValueError(
                    "production snapshots require release identity and status"
                )
        else:
            if any(field is not None for field in release_fields):
                raise ValueError("eval snapshots must not carry Release fields")
        expected = canonical_agent_definition_snapshot_digest(self)
        if self.snapshot_digest != expected:
            raise ValueError("snapshot_digest does not match snapshot content")
        return self

    @property
    def scope(self) -> AgentDefinitionScope:
        return AgentDefinitionScope(
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
            definition_id=self.definition_id,
        )

    @classmethod
    def from_release(
        cls,
        *,
        release: AgentRelease,
        version: AgentDefinitionVersion,
        resolved_at: datetime,
    ) -> Self:
        return cls._from_payload(
            {
                "definition_id": release.definition_id,
                "version_id": release.version_id,
                "definition_digest": release.definition_digest,
                "authority_issuer": release.authority_issuer,
                "namespace_id": release.namespace_id,
                "binding_purpose": BindingPurpose.PRODUCTION,
                "release_id": release.release_id,
                "release_revision": release.revision,
                "release_status": release.status,
                "model_policy_ref": version.model_policy_ref,
                "tool_profile_ref": version.tool_profile_ref,
                "skill_snapshot_digest": version.skill_snapshot_digest,
                "memory_policy_ref": version.memory_policy_ref,
                "security_policy_ref": version.security_policy_ref,
                "evaluation_profile_ref": version.evaluation_profile_ref,
                "runtime_profile_ref": version.runtime_profile_ref,
                "resolved_at": resolved_at,
            }
        )

    @classmethod
    def from_version(
        cls,
        *,
        version: AgentDefinitionVersion,
        resolved_at: datetime,
    ) -> Self:
        return cls._from_payload(
            {
                "definition_id": version.definition_id,
                "version_id": version.version_id,
                "definition_digest": version.definition_digest or "",
                "authority_issuer": version.authority_issuer,
                "namespace_id": version.namespace_id,
                "binding_purpose": BindingPurpose.EVAL,
                "model_policy_ref": version.model_policy_ref,
                "tool_profile_ref": version.tool_profile_ref,
                "skill_snapshot_digest": version.skill_snapshot_digest,
                "memory_policy_ref": version.memory_policy_ref,
                "security_policy_ref": version.security_policy_ref,
                "evaluation_profile_ref": version.evaluation_profile_ref,
                "runtime_profile_ref": version.runtime_profile_ref,
                "resolved_at": resolved_at,
            }
        )

    @classmethod
    def _from_payload(cls, payload: dict[str, object]) -> Self:
        values: dict[str, Any] = dict(payload)
        constructed = cls.model_construct(**values)
        digest = canonical_agent_definition_snapshot_digest(constructed)
        return cls.model_validate(
            constructed.model_copy(update={"snapshot_digest": digest}).model_dump()
        )


def canonical_agent_definition_snapshot_digest(
    snapshot: AgentDefinitionSnapshot,
) -> str:
    """Hash snapshot content; excludes the digest field and Release-free state."""

    payload: dict[str, object] = {
        "authority_issuer": snapshot.authority_issuer,
        "binding_purpose": snapshot.binding_purpose.value,
        "definition_digest": snapshot.definition_digest,
        "definition_id": str(snapshot.definition_id),
        "evaluation_profile_ref": snapshot.evaluation_profile_ref,
        "memory_policy_ref": snapshot.memory_policy_ref,
        "model_policy_ref": snapshot.model_policy_ref,
        "namespace_id": snapshot.namespace_id,
        "release_id": None if snapshot.release_id is None else str(snapshot.release_id),
        "release_revision": snapshot.release_revision,
        "release_status": (
            None if snapshot.release_status is None else snapshot.release_status.value
        ),
        "resolved_at": snapshot.resolved_at.isoformat(),
        "runtime_profile_ref": snapshot.runtime_profile_ref,
        "schema_version": snapshot.snapshot_schema_version,
        "security_policy_ref": snapshot.security_policy_ref,
        "skill_snapshot_digest": snapshot.skill_snapshot_digest,
        "tool_profile_ref": snapshot.tool_profile_ref,
        "version_id": str(snapshot.version_id),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()


def version_digest_matches_snapshot(
    version: AgentDefinitionVersion,
    snapshot: AgentDefinitionSnapshot,
) -> bool:
    """Deterministic digest agreement used by recovery; no Registry read."""
    return (
        version.version_id == snapshot.version_id
        and version.definition_id == snapshot.definition_id
        and (version.definition_digest or "") == snapshot.definition_digest
        and canonical_agent_definition_digest(version) == snapshot.definition_digest
    )
