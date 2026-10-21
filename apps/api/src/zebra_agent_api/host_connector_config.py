"""Explicit approved connector DTO; historical domain parsing remains unchanged."""

from __future__ import annotations

from typing import Any

from agent_core.domain.host_connectors import HostConnectorProfileVersion, HostConnectorStatus
from agent_storage.postgres.host_auth import _https_origin

_FIELDS = {
    "hostAppId": "host_app_id",
    "connectorId": "connector_id",
    "profileRevision": "profile_revision",
    "baseUri": "base_uri",
    "manifestPath": "manifest_path",
    "invokePathTemplate": "invoke_path_template",
    "reconcilePathTemplate": "reconcile_path_template",
    "supportedProtocolVersions": "supported_protocol_versions",
    "workloadIdentityRef": "workload_identity_ref",
    "credentialRef": "credential_ref",
    "networkPolicyRef": "network_policy_ref",
    "manifestBindingPolicy": "manifest_binding_policy",
    "status": "status",
}


def profile_from_wire(value: object, host_app_id: str) -> HostConnectorProfileVersion:
    if not isinstance(value, dict) or set(value) != set(_FIELDS):
        raise ValueError("invalid approved connector fields")
    revision = value["profileRevision"]
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise ValueError("invalid approved profile revision")
    for field in _FIELDS.keys() - {"profileRevision", "supportedProtocolVersions"}:
        content = value[field]
        if content is None and field in {"reconcilePathTemplate", "networkPolicyRef"}:
            continue
        if (
            not isinstance(content, str)
            or not content
            or content != content.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in content)
        ):
            raise ValueError("invalid connector text")
    versions = value["supportedProtocolVersions"]
    if (
        not isinstance(versions, list)
        or not 1 <= len(versions) <= 8
        or any(
            not isinstance(v, str)
            or not v
            or v != v.strip()
            or len(v) > 128
            or any(ord(c) < 32 or ord(c) == 127 for c in v)
            for v in versions
        )
    ):
        raise ValueError("invalid connector protocol versions")
    _https_origin(value["baseUri"], "baseUri")
    if value["hostAppId"] != host_app_id or value["status"] != "published":
        raise ValueError("connector Host/status differs from approval")
    if value["manifestBindingPolicy"] not in {"declared", "legacy"}:
        raise ValueError("explicit manifest policy required")
    mapped = {native: value[wire] for wire, native in _FIELDS.items()}
    mapped["supported_protocol_versions"] = tuple(versions)
    mapped["status"] = HostConnectorStatus.PUBLISHED
    return HostConnectorProfileVersion.model_validate(mapped)


def profile_wire(profile: HostConnectorProfileVersion | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    native = profile.model_dump(mode="json")
    # Legacy nullable policy is omitted by the domain serializer, but explicit on this wire.
    result = {wire: native.get(field) for wire, field in _FIELDS.items()}
    result["profileDigest"] = profile.profile_digest
    return result
