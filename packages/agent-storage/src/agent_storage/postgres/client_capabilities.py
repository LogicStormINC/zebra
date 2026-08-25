"""PostgreSQL adapter for published frontend capability profiles and bindings.

Revision rows are insert-only: the same revision replays only with the
same digest, a different digest fails closed, and revoked profiles stop
accepting new namespace bindings (ADR-CLIENT-01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_core.domain.client_capabilities import (
    ClientCapabilityError,
    FrontendCapabilityBinding,
    FrontendCapabilityProfileVersion,
    ProfileLifecycle,
    validate_profile_for_publish,
)
from agent_core.ports.client_capability_registry import ClientCapabilityRegistryPort
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase


class ClientCapabilityConflictError(ClientCapabilityError):
    pass


class ClientCapabilityCasError(ClientCapabilityError):
    pass


_LIFECYCLE_ORDER = {
    ProfileLifecycle.PUBLISHED: 0,
    ProfileLifecycle.DEPRECATED: 1,
    ProfileLifecycle.REVOKED: 2,
}


class PostgresClientCapabilityRegistry(ClientCapabilityRegistryPort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._namespace = self._database.deployment_namespace

    def publish_profile(self, profile: FrontendCapabilityProfileVersion) -> None:
        validate_profile_for_publish(profile)
        stored = profile.model_copy(
            update={"published_at": profile.published_at or datetime.now(UTC)}
        )
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT profile_digest, lifecycle FROM frontend_capability_profiles
                WHERE deployment_namespace = %s AND frontend_app_id = %s
                    AND revision = %s
                """,
                (self._namespace, profile.frontend_app_id, profile.revision),
            ).fetchone()
            if existing is not None:
                if existing["profile_digest"] != profile.profile_digest:
                    raise ClientCapabilityConflictError(
                        "profile revision is immutable; a different digest for"
                        " the same revision fails closed"
                    )
                return  # same revision + same digest replays
            connection.execute(
                """
                INSERT INTO frontend_capability_profiles (
                    deployment_namespace, frontend_app_id, revision,
                    profile_digest, lifecycle, profile_json, published_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, frontend_app_id, revision)
                    DO NOTHING
                """,
                (
                    self._namespace,
                    stored.frontend_app_id,
                    stored.revision,
                    stored.profile_digest,
                    stored.lifecycle.value,
                    Jsonb(stored.model_dump(mode="json")),
                    stored.published_at,
                ),
            )

    def get_profile(
        self, frontend_app_id: str, revision: int
    ) -> FrontendCapabilityProfileVersion | None:
        with self._database.connect() as connection:
            row = self._row_for(connection, frontend_app_id, revision)
        return None if row is None else _profile_from_row(row)

    def get_latest_profile(
        self, frontend_app_id: str
    ) -> FrontendCapabilityProfileVersion | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT profile_json FROM frontend_capability_profiles
                WHERE deployment_namespace = %s AND frontend_app_id = %s
                ORDER BY revision DESC
                LIMIT 1
                """,
                (self._namespace, frontend_app_id),
            ).fetchone()
        return None if row is None else _profile_from_row(row)

    def set_lifecycle(
        self,
        frontend_app_id: str,
        revision: int,
        lifecycle: ProfileLifecycle,
    ) -> None:
        with self._database.connect() as connection:
            row = self._row_for(connection, frontend_app_id, revision)
            if row is None:
                raise ClientCapabilityConflictError("profile revision not found")
            current = ProfileLifecycle(row["lifecycle"])
            if lifecycle is current:
                return
            if _LIFECYCLE_ORDER[lifecycle] <= _LIFECYCLE_ORDER[current]:
                raise ClientCapabilityConflictError(
                    "lifecycle may only move forward: published -> deprecated"
                    " -> revoked"
                )
            updated = connection.execute(
                """
                UPDATE frontend_capability_profiles
                SET lifecycle = %s
                WHERE deployment_namespace = %s AND frontend_app_id = %s
                    AND revision = %s AND lifecycle = %s
                RETURNING revision
                """,
                (
                    lifecycle.value,
                    self._namespace,
                    frontend_app_id,
                    revision,
                    current.value,
                ),
            ).fetchone()
            if updated is None:
                raise ClientCapabilityConflictError(
                    "lifecycle transition raced with another writer"
                )

    def save_binding(
        self, binding: FrontendCapabilityBinding, *, expected_binding_revision: int
    ) -> FrontendCapabilityBinding:
        with self._database.connect() as connection:
            profile = connection.execute(
                """
                SELECT lifecycle FROM frontend_capability_profiles
                WHERE deployment_namespace = %s AND frontend_app_id = %s
                    AND revision = %s AND profile_digest = %s
                """,
                (
                    self._namespace,
                    binding.frontend_app_id,
                    binding.revision,
                    binding.profile_digest,
                ),
            ).fetchone()
            if profile is None:
                raise ClientCapabilityConflictError(
                    "binding references an unpublished profile revision"
                )
            if profile["lifecycle"] == ProfileLifecycle.REVOKED.value:
                raise ClientCapabilityConflictError(
                    "revoked profiles do not accept new bindings"
                )
            existing = connection.execute(
                """
                SELECT binding_revision FROM frontend_capability_bindings
                WHERE deployment_namespace = %s AND binding_id = %s
                """,
                (self._namespace, binding.binding_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO frontend_capability_bindings (
                        deployment_namespace, binding_id, host_app_id,
                        namespace_id, frontend_app_id, revision,
                        profile_digest, binding_revision, bound_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self._namespace,
                        binding.binding_id,
                        binding.host_app_id,
                        binding.namespace_id,
                        binding.frontend_app_id,
                        binding.revision,
                        binding.profile_digest,
                        binding.binding_revision,
                        binding.bound_at,
                    ),
                )
                return binding
            current_revision = int(existing["binding_revision"])
            if current_revision != expected_binding_revision:
                raise ClientCapabilityCasError(
                    "binding update raced; expected revision is stale"
                )
            if binding.binding_revision != current_revision + 1:
                raise ClientCapabilityCasError(
                    "binding revisions may only increase by one"
                )
            connection.execute(
                """
                UPDATE frontend_capability_bindings
                SET profile_digest = %s, binding_revision = %s
                WHERE deployment_namespace = %s AND binding_id = %s
                    AND binding_revision = %s
                """,
                (
                    binding.profile_digest,
                    binding.binding_revision,
                    self._namespace,
                    binding.binding_id,
                    current_revision,
                ),
            )
            return binding

    def get_binding(
        self, binding_id: Any
    ) -> FrontendCapabilityBinding | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM frontend_capability_bindings
                WHERE deployment_namespace = %s AND binding_id = %s
                """,
                (self._namespace, binding_id),
            ).fetchone()
        if row is None:
            return None
        return FrontendCapabilityBinding(
            binding_id=row["binding_id"],
            deployment_namespace=row["deployment_namespace"],
            host_app_id=row["host_app_id"],
            namespace_id=row["namespace_id"],
            frontend_app_id=row["frontend_app_id"],
            revision=int(row["revision"]),
            profile_digest=row["profile_digest"],
            binding_revision=int(row["binding_revision"]),
            bound_at=row["bound_at"],
        )

    def _row_for(
        self, connection: Any, frontend_app_id: str, revision: int
    ) -> Any:
        return connection.execute(
            """
            SELECT profile_json, lifecycle FROM frontend_capability_profiles
            WHERE deployment_namespace = %s AND frontend_app_id = %s
                AND revision = %s
            """,
            (self._namespace, frontend_app_id, revision),
        ).fetchone()


def _profile_from_row(row: Any) -> FrontendCapabilityProfileVersion:
    return FrontendCapabilityProfileVersion.model_validate(row["profile_json"])
