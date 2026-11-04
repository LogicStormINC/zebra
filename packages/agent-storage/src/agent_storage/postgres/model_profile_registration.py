"""Atomic durable registration and exact scoped lookup for model profiles."""

from typing import Any
from uuid import UUID

from agent_core.domain.runtime_assembly import RuntimeProviderProfile
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.runtime_bundle_types import ArtifactPin, BundleScope
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase


class ModelProfileRegistrationConflict(ValueError):
    pass


class PostgresModelProfileRegistrations:
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def _scope(self, scope: BundleScope) -> str:
        return json_digest([self.database.deployment_namespace, scope.model_dump(mode="json")])

    def register(
        self,
        scope: BundleScope,
        operation_id: UUID,
        model_config_id: str,
        revision: int,
        request_digest: str,
        profile: RuntimeProviderProfile,
    ) -> None:
        scoped = self._scope(scope)
        with self.database.connect() as connection, connection.transaction():
            connection.execute(
                """INSERT INTO model_profile_revisions
                   (scope_digest, model_config_id, revision, profile_id, profile, request_digest)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (scope_digest, model_config_id, revision) DO NOTHING""",
                (scoped, model_config_id, revision, profile.pin.id,
                 Jsonb(profile.model_dump(mode="json")), request_digest),
            )
            stored = connection.execute(
                """SELECT request_digest, profile FROM model_profile_revisions
                   WHERE scope_digest = %s AND model_config_id = %s AND revision = %s""",
                (scoped, model_config_id, revision),
            ).fetchone()
            if stored is None or (
                stored["request_digest"] != request_digest
                or stored["profile"] != profile.model_dump(mode="json")
            ):
                raise ModelProfileRegistrationConflict("model revision already registered")
            connection.execute(
                """INSERT INTO model_profile_registration_operations
                   (scope_digest, operation_id, model_config_id, revision)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (scoped, operation_id, model_config_id, revision),
            )
            operation = connection.execute(
                """SELECT model_config_id, revision FROM model_profile_registration_operations
                   WHERE scope_digest = %s AND operation_id = %s""",
                (scoped, operation_id),
            ).fetchone()
            if operation != {"model_config_id": model_config_id, "revision": revision}:
                raise ModelProfileRegistrationConflict("operation already registered")

    def lookup_operation(self, scope: BundleScope, operation_id: UUID) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT o.model_config_id, o.revision, r.profile, r.request_digest
                   FROM model_profile_registration_operations o
                   JOIN model_profile_revisions r USING (scope_digest, model_config_id, revision)
                   WHERE o.scope_digest = %s AND o.operation_id = %s""",
                (self._scope(scope), operation_id),
            ).fetchone()

    def resolve(self, scope: BundleScope, pin: ArtifactPin) -> RuntimeProviderProfile | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT profile FROM model_profile_revisions
                   WHERE scope_digest = %s AND profile_id = %s
                   AND profile->'pin' = %s""",
                (self._scope(scope), pin.id, Jsonb(pin.model_dump(mode="json"))),
            ).fetchone()
        return None if row is None else RuntimeProviderProfile.model_validate(row["profile"])
