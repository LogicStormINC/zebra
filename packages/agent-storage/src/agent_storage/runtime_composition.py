"""Explicit local/cloud storage selection for application composition roots."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.ports import ArtifactObjectStorePort
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.session import Session  # type: ignore[import-untyped]

from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.composition import ControlPlaneStores, sqlite_control_plane_stores
from agent_storage.postgres_composition import postgres_control_plane_stores


@dataclass(frozen=True, slots=True)
class CloudCompositionSettings:
    """Fully resolved, namespace-bound inputs for PostgreSQL composition."""

    dsn: str
    deployment_namespace: str
    memory_cursor_signing_key: bytes
    artifact_objects: ArtifactObjectStorePort
    history_scope: OpaqueAuthorityScope
    continuation_scope: OpaqueAuthorityScope


def compose_control_plane_stores(
    *,
    profile: str,
    database_path: str | Path,
    cloud: CloudCompositionSettings | None = None,
) -> ControlPlaneStores:
    """Select exactly one storage profile; cloud never falls back to SQLite."""
    if profile != "cloud":
        # ponytail: test profiles intentionally exercise the local composition;
        # only the explicit cloud profile may select PostgreSQL.
        return sqlite_control_plane_stores(database_path)
    resolved = cloud or cloud_composition_from_environment()
    if not resolved.dsn.strip():
        raise ValueError("cloud profile requires ZEBRA_DATABASE_URL")
    stores = postgres_control_plane_stores(
        resolved.dsn,
        deployment_namespace=resolved.deployment_namespace,
        memory_cursor_signing_key=resolved.memory_cursor_signing_key,
        artifact_objects=resolved.artifact_objects,
        history_scope=resolved.history_scope,
        continuation_scope=resolved.continuation_scope,
    )
    # ponytail: the cloud object supplies the local caller contract through
    # read/index facades; a second ControlPlaneStores authority would split facts.
    return cast(ControlPlaneStores, stores)


def cloud_composition_from_environment(
    env: Mapping[str, str] | None = None,
) -> CloudCompositionSettings:
    """Resolve the complete cloud bundle and fail before creating any stores."""
    values = os.environ if env is None else env
    signing_key = _required(values, "ZEBRA_MEMORY_CURSOR_SIGNING_KEY").encode("utf-8")
    if len(signing_key) < 32:
        raise ValueError("ZEBRA_MEMORY_CURSOR_SIGNING_KEY must contain at least 32 bytes")
    issuer = _required(values, "ZEBRA_AUTHORITY_ISSUER")
    history_scope = OpaqueAuthorityScope(
        authority_issuer=issuer,
        namespace_id=_required(values, "ZEBRA_HISTORY_SCOPE_NAMESPACE"),
    )
    continuation_scope = OpaqueAuthorityScope(
        authority_issuer=issuer,
        namespace_id=_required(values, "ZEBRA_CONTINUATION_SCOPE_NAMESPACE"),
    )
    endpoint = _required(values, "ZEBRA_S3_ENDPOINT")
    bucket = _required(values, "ZEBRA_S3_BUCKET")
    client = Session().create_client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_required(values, "ZEBRA_S3_ACCESS_KEY"),
        aws_secret_access_key=_required(values, "ZEBRA_S3_SECRET_KEY"),
        aws_session_token=_optional(values, "ZEBRA_S3_SESSION_TOKEN"),
        region_name=_optional(values, "ZEBRA_S3_REGION") or "us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return CloudCompositionSettings(
        dsn=_required(values, "ZEBRA_DATABASE_URL"),
        deployment_namespace=_required(values, "ZEBRA_DEPLOYMENT_NAMESPACE"),
        memory_cursor_signing_key=signing_key,
        artifact_objects=S3ArtifactObjectStore(
            cast(Any, client),
            bucket=bucket,
            key_prefix=_optional(values, "ZEBRA_S3_KEY_PREFIX") or "zebra/artifacts/v1",
        ),
        history_scope=history_scope,
        continuation_scope=continuation_scope,
    )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise ValueError(f"cloud profile requires {name}")
    return value


def _optional(values: Mapping[str, str], name: str) -> str | None:
    value = values.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
