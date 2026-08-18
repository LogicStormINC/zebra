"""Outbound Host connector profiles and namespace bindings.

ADR-017 / plan section 4.3: inbound trust (`HostAuthorityRegistry`) and
outbound connection (`HostConnectorProfileVersion` + `HostConnectorBinding`)
are separate registries. Profiles are immutable per revision; updates create
a new revision. Secrets never enter the models — only bounded references.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_BASE_URI_LENGTH = 2048
MAX_PATH_TEMPLATE_LENGTH = 256
MAX_REFERENCE_LENGTH = 256
MAX_POLICY_REF_LENGTH = 256
MAX_PROTOCOL_VERSIONS = 8
PATH_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._~/-]*$")


class HostConnectorStatus(StrEnum):
    """Lifecycle of one connector profile binding surface."""

    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"


class HostConnectorProfileVersion(BaseModel):
    """One immutable outbound connection profile revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host_app_id: str = Field(min_length=1, max_length=128)
    connector_id: str = Field(min_length=1, max_length=128)
    profile_revision: int = Field(ge=1)
    base_uri: str = Field(min_length=1, max_length=MAX_BASE_URI_LENGTH)
    manifest_path: str = Field(min_length=1, max_length=MAX_PATH_TEMPLATE_LENGTH)
    invoke_path_template: str = Field(min_length=1, max_length=MAX_PATH_TEMPLATE_LENGTH)
    reconcile_path_template: str | None = Field(
        default=None, max_length=MAX_PATH_TEMPLATE_LENGTH
    )
    supported_protocol_versions: tuple[str, ...] = Field(min_length=1)
    workload_identity_ref: str = Field(min_length=1, max_length=MAX_REFERENCE_LENGTH)
    credential_ref: str = Field(min_length=1, max_length=MAX_REFERENCE_LENGTH)
    network_policy_ref: str | None = Field(default=None, max_length=MAX_POLICY_REF_LENGTH)
    status: HostConnectorStatus = HostConnectorStatus.PUBLISHED

    @model_validator(mode="after")
    def _validate_profile(self) -> Self:
        parts = urlsplit(self.base_uri)
        if parts.scheme != "https" or not parts.netloc or parts.query or parts.fragment:
            raise ValueError("connector base_uri must be a bare HTTPS origin")
        for path in (self.manifest_path, self.invoke_path_template, self.reconcile_path_template):
            if path is None:
                continue
            if not path.startswith("/") or not PATH_SEGMENT_PATTERN.fullmatch(path[1:]):
                raise ValueError(f"connector path template is invalid: {path!r}")
        versions = self.supported_protocol_versions
        if len(versions) > MAX_PROTOCOL_VERSIONS or len(set(versions)) != len(versions):
            raise ValueError("supported protocol versions are invalid")
        for forbidden in ("secret", "token", "password"):
            if forbidden in self.credential_ref.lower():
                raise ValueError("credential references must not embed secret material")
        return self

    @property
    def profile_digest(self) -> str:
        canonical = {
            "hostAppId": self.host_app_id,
            "connectorId": self.connector_id,
            "profileRevision": self.profile_revision,
            "baseUri": self.base_uri,
            "manifestPath": self.manifest_path,
            "invokePathTemplate": self.invoke_path_template,
            "reconcilePathTemplate": self.reconcile_path_template,
            "supportedProtocolVersions": list(self.supported_protocol_versions),
            "workloadIdentityRef": self.workload_identity_ref,
            "credentialRef": self.credential_ref,
            "networkPolicyRef": self.network_policy_ref,
            "status": self.status.value,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class HostConnectorBinding(BaseModel):
    """Resolve one host_app_id + namespace_id to a pinned profile revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host_app_id: str = Field(min_length=1, max_length=128)
    namespace_id: str = Field(min_length=1, max_length=512)
    connector_id: str = Field(min_length=1, max_length=128)
    profile_revision: int = Field(ge=1)
    binding_revision: int = Field(ge=1)
    active: bool = True

    @model_validator(mode="after")
    def _validate_binding(self) -> Self:
        if not self.host_app_id.strip() or not self.namespace_id.strip():
            raise ValueError("connector binding identifiers must be non-blank")
        return self


def accepts_new_tasks(status: HostConnectorStatus) -> bool:
    """Only published connectors may bind new Tasks (plan lifecycle table)."""

    return status is HostConnectorStatus.PUBLISHED


def fails_closed_for_running_tasks(status: HostConnectorStatus) -> bool:
    """Revoked connectors fail closed for already-bound Tasks."""

    return status is HostConnectorStatus.REVOKED
