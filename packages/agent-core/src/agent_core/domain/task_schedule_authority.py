"""User ownership and secret-free authority snapshots for Task schedules."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskScheduleId
from agent_core.domain.task_bindings import host_context_digest

MAX_TEMPLATE_BYTES = 65_536
_FORBIDDEN_TEMPLATE_KEYS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)


def _normalized_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _check_secret_keys(value: object, *, path: str = "task_template") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).strip().lower().replace("-", "_")
            if any(fragment in lowered for fragment in _FORBIDDEN_TEMPLATE_KEYS):
                raise ValueError(f"{path} must not persist credential-like fields")
            _check_secret_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _check_secret_keys(nested, path=f"{path}[{index}]")


def _canonical_template_json(value: dict[str, object]) -> str:
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("task_template.prompt must be a non-blank string")
    if "execute" in value:
        raise ValueError("task_template.execute is controlled by the materializer")
    _check_secret_keys(value)
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        encoded = canonical.encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("task_template must be JSON-compatible") from exc
    if len(encoded) > MAX_TEMPLATE_BYTES:
        raise ValueError("task_template exceeds the byte budget")
    return canonical


class ScheduleOwner(BaseModel):
    """Opaque user ownership boundary copied from verified Host authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    deployment_namespace: str = Field(max_length=256)
    tenant_id: str = Field(max_length=256)
    workspace_id: str = Field(max_length=512)
    principal_id: str = Field(max_length=256)
    host_app_id: str = Field(max_length=128)

    @field_validator(
        "deployment_namespace", "tenant_id", "workspace_id", "principal_id", "host_app_id"
    )
    @classmethod
    def normalize_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "owner field")
        return _normalized_text(value, field_name=field_name)


class ScheduledTaskTemplate(BaseModel):
    """Canonical Task payload; callers only receive decoded copies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_json: str

    @model_validator(mode="before")
    @classmethod
    def encode_payload(cls, value: object) -> object:
        if not isinstance(value, dict) or "payload" not in value or "payload_json" in value:
            return value
        copied = dict(value)
        payload = copied.pop("payload")
        if not isinstance(payload, dict):
            raise ValueError("task_template.payload must be an object")
        copied["payload_json"] = _canonical_template_json(payload)
        return copied

    @field_validator("payload_json")
    @classmethod
    def validate_payload_json(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("task_template must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("task_template must encode an object")
        return _canonical_template_json(payload)

    @property
    def payload(self) -> dict[str, object]:
        decoded = json.loads(self.payload_json)
        assert isinstance(decoded, dict)
        return decoded

    @property
    def template_digest(self) -> str:
        return hashlib.sha256(self.payload_json.encode()).hexdigest()


class ScheduleAuthorityBinding(BaseModel):
    """Secret-free authority evidence revalidated before every firing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: UUID
    schedule_id: TaskScheduleId
    owner: ScheduleOwner
    host_context: HostContextEnvelope
    host_capability_digest: str
    agent_definition_digest: str
    policy_digest: str
    extension_snapshot_digest: str
    binding_revision: int = Field(ge=1)
    bound_at: datetime
    revoked_at: datetime | None = None

    @field_validator(
        "host_capability_digest",
        "agent_definition_digest",
        "policy_digest",
        "extension_snapshot_digest",
    )
    @classmethod
    def normalize_digest(cls, value: str, info: object) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            field_name = getattr(info, "field_name", "digest")
            raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        return normalized

    @field_validator("bound_at", "revoked_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None, info: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            field_name = getattr(info, "field_name", "timestamp")
            raise ValueError(f"{field_name} must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_revocation(self) -> Self:
        if self.revoked_at is not None and self.revoked_at < self.bound_at:
            raise ValueError("revoked_at must not precede bound_at")
        principals = tuple(
            ref.resource_id
            for ref in self.host_context.resource_refs
            if ref.resource_type == "principal"
        )
        if principals != (self.owner.principal_id,):
            raise ValueError("host_context must bind exactly the Schedule owner principal")
        if (
            self.host_context.namespace_id != self.owner.tenant_id
            or self.host_context.workspace_ref != self.owner.workspace_id
            or self.host_context.host_app_id != self.owner.host_app_id
        ):
            raise ValueError("host_context identity must match the Schedule owner")
        if self.host_capability_digest != host_context_digest(self.host_context):
            raise ValueError("host_capability_digest must match host_context")
        for scope in ("agent.run", "schedule.manage"):
            self.host_context.require_scope(scope)
        return self

    def revoke(self, *, at: datetime) -> ScheduleAuthorityBinding:
        if self.revoked_at is not None:
            raise ValueError("Schedule authority is already revoked")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be timezone-aware")
        moment = at.astimezone(UTC)
        if moment < self.bound_at:
            raise ValueError("revocation cannot precede binding")
        return ScheduleAuthorityBinding.model_validate(
            {
                **self.model_dump(),
                "binding_revision": self.binding_revision + 1,
                "revoked_at": moment,
            }
        )


class ScheduleExecutionAuthority(BaseModel):
    """Fresh short-lived authority returned by the Host workload exchange."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host_context: HostContextEnvelope
    authority_issuer: str = Field(max_length=2_048)
    grant_id: str = Field(max_length=512)
    subject_ref: str = Field(max_length=512)
    algorithm: Literal["RS256", "ES256"]

    @field_validator("authority_issuer", "grant_id", "subject_ref")
    @classmethod
    def normalize_execution_text(cls, value: str, info: object) -> str:
        return _normalized_text(
            value, field_name=str(getattr(info, "field_name", "authority field"))
        )

    @model_validator(mode="after")
    def validate_principal(self) -> Self:
        principals = tuple(
            ref.resource_id
            for ref in self.host_context.resource_refs
            if ref.resource_type == "principal"
        )
        if self.grant_id != self.host_context.grant_id:
            raise ValueError("grant_id must match host_context")
        if principals != (self.subject_ref,):
            raise ValueError("subject_ref must match the Host principal")
        return self
