"""Immutable Task binding snapshots (ADR-017 decision 5).

Admission freezes every running capability into a ``TaskBindingSnapshot``;
Workers consume the snapshot and never re-discover manifests. Snapshots carry
digests and bounded references only — no secrets, no raw JWTs, no Host
credentials.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.agent_capabilities import (
    Capability,
    capability_set,
    intersect_capabilities,
)
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostGrantExpiredError,
    HostGrantMismatchError,
    HostGrantScopeError,
    HostResourceRef,
)
from agent_core.domain.host_capability_manifests import HostCapabilityManifestV1

MAX_DIGEST_LENGTH = 64
MAX_NAMESPACE_LENGTH = 512


class AgentCapabilityCeilingSnapshot(BaseModel):
    """Capability ceiling resolved from one Agent Definition release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_snapshot_digest: str = Field(min_length=64, max_length=MAX_DIGEST_LENGTH)
    capability_profile_ref: str = Field(min_length=1, max_length=256)
    capabilities: frozenset[Capability]
    resolved_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        object.__setattr__(self, "capabilities", capability_set(sorted(self.capabilities)))
        if self.resolved_at.tzinfo is None:
            raise ValueError("capability ceiling resolved_at must be timezone-aware")
        return self


class HostCapabilitySnapshot(BaseModel):
    """Host-side capabilities frozen from a manifest and grant at admission."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host_app_id: str = Field(min_length=1, max_length=128)
    authority_issuer: str = Field(min_length=1, max_length=256)
    namespace_id: str = Field(min_length=1, max_length=MAX_NAMESPACE_LENGTH)
    grant_digest: str = Field(min_length=64, max_length=MAX_DIGEST_LENGTH)
    grant_expires_at: datetime | None = None
    connector_id: str = Field(min_length=1, max_length=128)
    connector_profile_revision: int = Field(ge=1)
    connector_profile_digest: str = Field(min_length=64, max_length=MAX_DIGEST_LENGTH)
    manifest_digest: str = Field(min_length=64, max_length=MAX_DIGEST_LENGTH)
    capabilities: frozenset[Capability]
    resource_binding_digest: str = Field(min_length=64, max_length=MAX_DIGEST_LENGTH)
    bound_at: datetime
    host_context: HostContextEnvelope | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        object.__setattr__(self, "capabilities", capability_set(sorted(self.capabilities)))
        for stamp in (self.grant_expires_at, self.bound_at):
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError("host capability timestamps must be timezone-aware")
        return self

    @classmethod
    def from_manifest(
        cls,
        manifest: HostCapabilityManifestV1,
        *,
        authority_issuer: str,
        namespace_id: str,
        grant_digest: str,
        grant_expires_at: datetime | None,
        connector_id: str,
        connector_profile_digest: str,
        host_context: HostContextEnvelope | None = None,
        bound_at: datetime | None = None,
    ) -> HostCapabilitySnapshot:
        """Freeze a manifest (plus its grant anchors) into a snapshot."""

        manifest_capabilities = {
            capability for tool in manifest.tools for capability in tool.capabilities
        }
        binding_digest_source = hashlib.sha256(
            json.dumps(
                [
                    {
                        "tool": tool.name,
                        "bindings": [
                            {
                                "argumentPointer": rule.argument_pointer,
                                "resourceType": rule.resource_type,
                                "required": rule.required,
                            }
                            for rule in tool.resource_bindings
                        ],
                    }
                    for tool in manifest.tools
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return cls(
            host_app_id=manifest.host_app_id,
            authority_issuer=authority_issuer,
            namespace_id=namespace_id,
            grant_digest=grant_digest,
            grant_expires_at=grant_expires_at,
            connector_id=connector_id,
            connector_profile_revision=manifest.connector_profile_revision,
            connector_profile_digest=connector_profile_digest,
            manifest_digest=manifest.manifest_digest,
            capabilities=frozenset(manifest_capabilities),
            resource_binding_digest=binding_digest_source,
            bound_at=bound_at or datetime.now(UTC),
            host_context=host_context,
        )


def host_context_digest(context: HostContextEnvelope) -> str:
    """Digest the complete, validated and secret-free Host authority context."""

    encoded = json.dumps(
        context.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class TaskBindingSnapshot(BaseModel):
    """The one immutable binding of a Task to Definition + Host + policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str = Field(min_length=1, max_length=128)
    agent_capability_ceiling: AgentCapabilityCeilingSnapshot
    host_capability: HostCapabilitySnapshot
    zebra_policy_digest: str = Field(min_length=64, max_length=MAX_DIGEST_LENGTH)
    effective_capabilities: frozenset[Capability]
    binding_revision: int = Field(ge=1)
    bound_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        object.__setattr__(
            self,
            "effective_capabilities",
            capability_set(sorted(self.effective_capabilities)),
        )
        if self.bound_at.tzinfo is None:
            raise ValueError("task binding bound_at must be timezone-aware")
        return self

    @property
    def binding_digest(self) -> str:
        canonical = {
            "taskId": self.task_id,
            "definitionDigest": self.agent_capability_ceiling.definition_snapshot_digest,
            "hostManifestDigest": self.host_capability.manifest_digest,
            "connectorProfileDigest": self.host_capability.connector_profile_digest,
            "grantDigest": self.host_capability.grant_digest,
            "zebraPolicyDigest": self.zebra_policy_digest,
            "effectiveCapabilities": sorted(self.effective_capabilities),
            "bindingRevision": self.binding_revision,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def require_host_thread(context: HostContextEnvelope) -> HostResourceRef:
    """Resolve exactly one opaque Host thread; never infer it from a Task UUID."""
    refs = [ref for ref in context.resource_refs if ref.resource_type == "thread"]
    if len(refs) != 1:
        raise HostGrantScopeError("Host Grant requires one unambiguous thread")
    return refs[0]


def task_bound_host_thread(binding: TaskBindingSnapshot, *, task_id: str) -> HostResourceRef:
    """Resolve the immutable Task-to-Host mapping without checking old expiry."""
    if not isinstance(binding, TaskBindingSnapshot) or binding.task_id != task_id:
        raise HostGrantMismatchError("Task binding target conflicts")
    host = binding.host_capability
    bound = host.host_context
    if (
        bound is None
        or host.host_app_id != bound.host_app_id
        or host.namespace_id != bound.namespace_id
        or host.grant_digest != host_context_digest(bound)
    ):
        raise HostGrantMismatchError("Task binding Host authority conflicts")
    _host_principal(bound)
    return require_host_thread(bound)


def require_task_host_context(
    binding: TaskBindingSnapshot,
    context: HostContextEnvelope,
    *,
    task_id: str,
    now: datetime,
    authority_issuer: str | None = None,
    run_id: str | None = None,
) -> HostResourceRef:
    """Fence a verified current Grant; signature and atomic jti remain upstream."""
    if now.tzinfo is None:
        raise HostGrantMismatchError("Host authorization time must be timezone-aware")
    if context.expires_at is None or context.expires_at <= now:
        raise HostGrantExpiredError("Host Grant has expired or lacks an expiry")
    thread = task_bound_host_thread(binding, task_id=task_id)
    bound = binding.host_capability.host_context
    assert bound is not None
    identity = ("host_app_id", "namespace_id", "origin", "workspace_ref")
    if any(getattr(bound, field) != getattr(context, field) for field in identity):
        raise HostGrantMismatchError(
            "Host Grant identity or workspace drifted from the Task binding"
        )
    if _host_principal(bound) != _host_principal(context):
        raise HostGrantMismatchError("Host Grant principal drifted from the Task binding")
    if (
        authority_issuer is not None
        and binding.host_capability.authority_issuer != authority_issuer
    ):
        raise HostGrantMismatchError("Host Grant authority issuer drifted from the Task binding")
    if require_host_thread(context) != thread:
        raise HostGrantScopeError("Host Grant thread conflicts with the Task binding")
    context.require_resource(thread)
    runs = [ref for ref in context.resource_refs if ref.resource_type == "run"]
    if len(runs) > 1 or (run_id is not None and runs != [HostResourceRef(type="run", id=run_id)]):
        raise HostGrantScopeError("Host Grant Run target conflicts")
    return thread


def require_legacy_artifact_host_context(
    prepared: HostContextEnvelope, current: HostContextEnvelope, *, now: datetime
) -> None:
    """Compare historical ownership only; this never creates execution authority."""
    if now.tzinfo is None or current.expires_at is None or current.expires_at <= now:
        raise HostGrantExpiredError("Artifact read requires a current Host Grant")
    prepared.require_scope("artifact.read")
    current.require_scope("artifact.read")
    if any(
        getattr(prepared, key) != getattr(current, key)
        for key in ("host_app_id", "namespace_id", "workspace_ref", "origin")
    ) or _host_principal(prepared) != _host_principal(current):
        raise HostGrantMismatchError("Historical artifact owner conflicts")
    if require_host_thread(prepared) != require_host_thread(current):
        raise HostGrantScopeError("Historical artifact thread conflicts")


def _host_principal(context: HostContextEnvelope) -> HostResourceRef:
    refs = [ref for ref in context.resource_refs if ref.resource_type == "principal"]
    if len(refs) != 1:
        raise HostGrantScopeError("Host Grant requires one unambiguous principal")
    return refs[0]


def compute_effective_capabilities(
    ceiling: AgentCapabilityCeilingSnapshot,
    host: HostCapabilitySnapshot,
    *,
    zebra_policy_capabilities: frozenset[Capability],
) -> frozenset[Capability]:
    """EffectiveCapabilities = ceiling ∩ manifest ∩ grant ∩ Zebra policy."""

    return intersect_capabilities(
        ceiling.capabilities,
        host.capabilities,
        zebra_policy_capabilities,
    )


def bind_task(
    task_id: str,
    *,
    ceiling: AgentCapabilityCeilingSnapshot,
    host: HostCapabilitySnapshot,
    zebra_policy_digest: str,
    zebra_policy_capabilities: frozenset[Capability],
) -> TaskBindingSnapshot:
    """Compute and freeze one Task binding (single call, no partial state)."""

    effective = compute_effective_capabilities(
        ceiling,
        host,
        zebra_policy_capabilities=zebra_policy_capabilities,
    )
    if not effective:
        raise ValueError("task binding produces an empty capability intersection")
    return TaskBindingSnapshot(
        task_id=task_id,
        agent_capability_ceiling=ceiling,
        host_capability=host,
        zebra_policy_digest=zebra_policy_digest,
        effective_capabilities=effective,
        binding_revision=1,
        bound_at=datetime.now(UTC),
    )
