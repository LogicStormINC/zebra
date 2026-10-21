"""Atomic immutable Definition Version storage, including the additive v2 sidecar."""

from __future__ import annotations

import json
from typing import Any

from agent_core.domain.agent_definitions import AgentDefinitionVersion
from agent_core.domain.bundle_definition import BundleDefinitionVersion, parse_definition_version

from agent_storage.postgres.agent_registry_common import AgentRegistryStorageError, _Jsonb

VERSION_FIELDS = tuple(AgentDefinitionVersion.model_fields)
VERSION_COLUMNS = ", ".join(VERSION_FIELDS)


def version_from_row(row: dict[str, Any], connection: Any) -> AgentDefinitionVersion:
    schema = row["schema_version"]
    if schema == "agent-definition/1":
        return parse_definition_version(dict(row))
    if schema not in {"agent-definition/2", "agent-definition/3"}:
        raise AgentRegistryStorageError("unsupported Definition Version schema")
    sidecar = connection.execute(
        "SELECT snapshot FROM agent_definition_bundle_versions WHERE authority_issuer=%s "
        "AND namespace_id=%s AND definition_id=%s AND version_id=%s",
        tuple(
            row[name]
            for name in ("authority_issuer", "namespace_id", "definition_id", "version_id")
        ),
    ).fetchone()
    if sidecar is None:
        raise AgentRegistryStorageError("Bundle Definition Version sidecar is missing")
    try:
        version = parse_definition_version(sidecar["snapshot"])
        if not isinstance(version, BundleDefinitionVersion) or any(
            getattr(version, name) != row[name] for name in VERSION_FIELDS
        ):
            raise ValueError("relational Version fields disagree with sidecar")
        return version
    except (ValueError, TypeError, KeyError) as exc:
        raise AgentRegistryStorageError("Bundle Definition Version sidecar is corrupt") from exc


def save_version(connection: Any, value: AgentDefinitionVersion) -> AgentDefinitionVersion:
    version = parse_definition_version(value)
    scope = version.scope.scope_key
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (json.dumps(["agent-definition-version", *map(str, scope)]),),
    )
    existing = connection.execute(
        f"SELECT {VERSION_COLUMNS} FROM agent_definition_versions WHERE authority_issuer=%s "
        "AND namespace_id=%s AND definition_id=%s AND version_id=%s",
        (*scope, version.version_id),
    ).fetchone()
    if existing is not None:
        durable = version_from_row(existing, connection)
        if durable.model_dump(mode="json", exclude={"created_at"}) != version.model_dump(
            mode="json", exclude={"created_at"}
        ):
            raise AgentRegistryStorageError("Version content changed under a reused version_id")
        return durable
    by_number = connection.execute(
        "SELECT version_id FROM agent_definition_versions WHERE authority_issuer=%s "
        "AND namespace_id=%s AND definition_id=%s AND version=%s",
        (*scope, version.version),
    ).fetchone()
    if by_number is not None:
        raise AgentRegistryStorageError(
            "Definition version number already exists with different content"
        )
    connection.execute(
        f"INSERT INTO agent_definition_versions ({VERSION_COLUMNS}) "
        f"VALUES ({', '.join(['%s'] * len(VERSION_FIELDS))})",
        tuple(getattr(version, name) for name in VERSION_FIELDS),
    )
    if isinstance(version, BundleDefinitionVersion):
        connection.execute(
            "INSERT INTO agent_definition_bundle_versions "
            "(authority_issuer,namespace_id,definition_id,version_id,snapshot) "
            "VALUES (%s,%s,%s,%s,%s)",
            (*scope, version.version_id, _Jsonb(version.model_dump(mode="json"))),
        )
    return version
