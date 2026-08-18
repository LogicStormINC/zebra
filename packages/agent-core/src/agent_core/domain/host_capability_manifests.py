"""Host Capability Manifest v1: the generic Host-to-Zebra tool protocol.

ADR-017 decision 5 fixes that running capabilities come from immutable
snapshots taken at admission. This module defines the manifest contract the
snapshots freeze: per-tool capabilities, required grant scopes, resource
binding rules with bounded JSON-pointer selectors, and canonical digests.

Selector safety (plan section 4): only single-segment JSON pointers over
top-level string arguments are accepted. JSONPath, scripts, templates or any
executable selector are rejected at validation time.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.agent_capabilities import (
    Capability,
    GrantScope,
    capability_set,
    grant_scope_set,
)

MANIFEST_SCHEMA_VERSION: Literal["zebra.host-capability-manifest/1"] = (
    "zebra.host-capability-manifest/1"
)
MANIFEST_PROTOCOL_VERSION = "host-capability-protocol/1"
MAX_MANIFEST_TOOLS = 128
MAX_RESOURCE_TYPE_LENGTH = 128
MAX_ARGUMENT_POINTER_SEGMENTS = 1
ARGUMENT_POINTER_PATTERN = re.compile(r"^/[A-Za-z0-9_.-]+$")
MATCH_MODE_EXACT: Literal["exact"] = "exact"


class ResourceBindingRule(BaseModel):
    """Bind one top-level tool argument to one Host resource type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    argument_pointer: str = Field(pattern=r"^/.+$")
    resource_type: str = Field(min_length=1, max_length=MAX_RESOURCE_TYPE_LENGTH)
    required: bool = True
    match_mode: Literal["exact"] = MATCH_MODE_EXACT

    @model_validator(mode="after")
    def _bound_selector(self) -> Self:
        pointer = self.argument_pointer.strip()
        if ARGUMENT_POINTER_PATTERN.fullmatch(pointer) is None:
            raise ValueError(
                "argument pointer must be a single-segment JSON pointer like '/event_id'"
            )
        segments = [segment for segment in pointer[1:].split("/") if segment]
        if len(segments) != MAX_ARGUMENT_POINTER_SEGMENTS:
            raise ValueError("argument pointer must address exactly one top-level argument")
        if not self.resource_type.strip() or self.match_mode != "exact":
            raise ValueError("resource binding rule is invalid")
        return self

    @property
    def argument_name(self) -> str:
        return self.argument_pointer.strip()[1:]


class HostToolContractV1(BaseModel):
    """Host-declared wrapper around one tool with binding semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    capabilities: frozenset[Capability]
    required_grant_scopes: frozenset[GrantScope]
    resource_bindings: tuple[ResourceBindingRule, ...] = ()
    effect_reconcile_capable: bool = False

    @model_validator(mode="after")
    def _validate_sets(self) -> Self:
        object.__setattr__(
            self, "capabilities", capability_set(sorted(self.capabilities))
        )
        object.__setattr__(
            self, "required_grant_scopes", grant_scope_set(sorted(self.required_grant_scopes))
        )
        if not self.capabilities:
            raise ValueError("host tool contract must declare at least one capability")
        names = [rule.argument_name for rule in self.resource_bindings]
        if len(set(names)) != len(names):
            raise ValueError("resource bindings must address distinct arguments")
        return self

    @property
    def contract_digest(self) -> str:
        canonical = {
            "name": self.name,
            "capabilities": sorted(self.capabilities),
            "requiredGrantScopes": sorted(self.required_grant_scopes),
            "resourceBindings": [
                {
                    "argumentPointer": rule.argument_pointer.strip(),
                    "resourceType": rule.resource_type.strip(),
                    "required": rule.required,
                    "matchMode": rule.match_mode,
                }
                for rule in self.resource_bindings
            ],
            "effectReconcileCapable": self.effect_reconcile_capable,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class HostCapabilityManifestV1(BaseModel):
    """Versioned, digest-pinned manifest of one Host's tool surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["zebra.host-capability-manifest/1"] = MANIFEST_SCHEMA_VERSION
    protocol_version: str = Field(min_length=1, max_length=64)
    host_app_id: str = Field(min_length=1, max_length=128)
    connector_profile_revision: int = Field(ge=1)
    workload_identity: str = Field(min_length=1, max_length=512)
    tools: tuple[HostToolContractV1, ...]

    @model_validator(mode="after")
    def _validate_tools(self) -> Self:
        if not self.tools or len(self.tools) > MAX_MANIFEST_TOOLS:
            raise ValueError("manifest tool count is outside its bounds")
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("manifest contains duplicate tool names")
        return self

    @property
    def manifest_digest(self) -> str:
        canonical = {
            "schemaVersion": self.schema_version,
            "protocolVersion": self.protocol_version,
            "hostAppId": self.host_app_id,
            "connectorProfileRevision": self.connector_profile_revision,
            "workloadIdentity": self.workload_identity,
            "tools": [
                {
                    "name": tool.name,
                    "contractDigest": tool.contract_digest,
                }
                for tool in self.tools
            ],
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
