"""Strict private operator template for the scoped Host management adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_storage import HostRegistryRecord
from agent_storage.postgres.host_management import HostManagementTrust

from zebra_agent_api.extension_request_body import _unique_object

_SCOPE_FIELDS = ("deploymentId", "deploymentNamespace", "audience", "productId", "environment")
_REGISTRY_FIELDS = {
    "hostAppId",
    "namespaceId",
    "issuer",
    "audience",
    "jwksUri",
    "allowedOrigins",
    "algorithms",
    "policyVersion",
    "active",
}


@dataclass(frozen=True)
class HostManagementConfig:
    trust: HostManagementTrust
    registry: HostRegistryRecord
    actions: frozenset[str]
    credential_sha256: str
    scope: dict[str, str]


def load_host_management_config(path: str | None, namespace: str | None) -> HostManagementConfig:
    if path is None or not Path(path).is_absolute():
        raise ValueError("private configuration required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}:
            raise ValueError("private regular configuration required")
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("configuration too large")
    value = json.loads(raw, object_pairs_hook=_unique_object)
    fields = {
        *_SCOPE_FIELDS,
        "trustRevision",
        "credentialSha256",
        "expiresAt",
        "actions",
        "registry",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid configuration fields")
    for field in _SCOPE_FIELDS:
        if not isinstance(value[field], str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value[field]
        ):
            raise ValueError("invalid management scope")
    if value["deploymentNamespace"] != namespace:
        raise ValueError("deployment namespace mismatch")
    revision = value["trustRevision"]
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise ValueError("invalid trust revision")
    digest = value["credentialSha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid credential digest")
    expiry = value["expiresAt"]
    if not isinstance(expiry, str) or not expiry.endswith("Z"):
        raise ValueError("UTC credential deadline required")
    expires_at = datetime.fromisoformat(expiry)
    actions = value["actions"]
    allowed = {"host-registry.read", "host-registry.write"}
    if (
        not isinstance(actions, list)
        or any(not isinstance(a, str) or a not in allowed for a in actions)
        or len(set(actions)) != len(actions)
    ):
        raise ValueError("invalid management actions")
    record = value["registry"]
    if (
        not isinstance(record, dict)
        or set(record) != _REGISTRY_FIELDS
        or record["active"] is not True
    ):
        raise ValueError("invalid approved registry template")
    if any(not isinstance(record[f], list) for f in ("algorithms", "allowedOrigins")):
        raise ValueError("invalid registry arrays")
    registry = HostRegistryRecord(
        host_app_id=record["hostAppId"],
        namespace_id=record["namespaceId"],
        issuer=record["issuer"],
        audience=record["audience"],
        jwks_uri=record["jwksUri"],
        allowed_origins=tuple(record["allowedOrigins"]),
        algorithms=tuple(record["algorithms"]),
        policy_version=record["policyVersion"],
    )
    fingerprint = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    trust = HostManagementTrust(
        deployment_id=value["deploymentId"],
        audience=value["audience"],
        product_id=value["productId"],
        environment=value["environment"],
        host_app_id=registry.host_app_id,
        namespace_id=registry.namespace_id,
        revision=revision,
        fingerprint=fingerprint,
        expires_at=expires_at,
    )
    return HostManagementConfig(
        trust, registry, frozenset(actions), digest, {f: value[f] for f in _SCOPE_FIELDS}
    )


def registry_wire(record: HostRegistryRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "hostAppId": record.host_app_id,
        "namespaceId": record.namespace_id,
        "issuer": record.issuer,
        "audience": record.audience,
        "jwksUri": record.jwks_uri,
        "allowedOrigins": list(record.allowed_origins),
        "algorithms": list(record.algorithms),
        "policyVersion": record.policy_version,
        "active": record.active,
    }
