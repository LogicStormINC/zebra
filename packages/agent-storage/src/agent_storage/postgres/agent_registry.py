"""Namespace-bound PostgreSQL Agent Definition Registry authority (v19)."""

from __future__ import annotations

from typing import Any

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionScope,
    AgentDefinitionVersion,
    AgentRelease,
    AgentReleaseStatus,
)
from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
    AgentReleaseId,
)

from agent_storage.postgres.agent_registry_common import AgentRegistryStorageError, _Jsonb
from agent_storage.postgres.agent_registry_drafts import AgentDraftAuthorityMixin
from agent_storage.postgres.agent_registry_evidence import AgentDefinitionEvalEvidence
from agent_storage.postgres.database import PostgresDatabase

__all__ = [
    "AgentDefinitionEvalEvidence",
    "AgentRegistryStorageError",
    "PostgresAgentRegistry",
]


class PostgresAgentRegistry(AgentDraftAuthorityMixin):
    """Definition metadata authority with CAS revisions and single-publish."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def get_definition(self, scope: AgentDefinitionScope) -> AgentDefinition | None:
        with self._database.connect() as connection:
            row = connection.execute(
                self._definition_query(),
                scope.scope_key,
            ).fetchone()
        return _definition_from_row(row) if row is not None else None

    def save_definition(
        self,
        definition: AgentDefinition,
        *,
        expected_revision: int | None = None,
    ) -> AgentDefinition:
        scope = definition.scope
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT revision FROM agent_definition_records"
                " WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s",
                scope.scope_key,
            ).fetchone()
            if existing is None:
                if expected_revision is not None:
                    raise AgentRegistryStorageError(
                        "cannot create a Definition with an expected revision"
                    )
                connection.execute(
                    """
                    INSERT INTO agent_definition_records (
                        authority_issuer, namespace_id, definition_id, name,
                        description, revision, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        definition.authority_issuer,
                        definition.namespace_id,
                        definition.definition_id,
                        definition.name,
                        definition.description,
                        definition.revision,
                        definition.created_at,
                    ),
                )
                return definition
            current = int(existing["revision"])
            if expected_revision is None or expected_revision != current:
                raise AgentRegistryStorageError(
                    f"Definition revision conflict: durable revision is {current}"
                )
            updated = definition.model_copy(update={"revision": current + 1})
            changed = connection.execute(
                """
                UPDATE agent_definition_records
                SET name = %s, description = %s, revision = %s
                WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s
                  AND revision = %s
                RETURNING revision
                """,
                (
                    updated.name,
                    updated.description,
                    updated.revision,
                    *scope.scope_key,
                    current,
                ),
            ).fetchone()
            if changed is None:
                raise AgentRegistryStorageError(
                    "Definition revision changed concurrently; retry from durable state"
                )
            return updated

    def get_version(
        self,
        scope: AgentDefinitionScope,
        version_id: AgentDefinitionVersionId,
    ) -> AgentDefinitionVersion | None:
        with self._database.connect() as connection:
            row = connection.execute(
                self._version_query() + " AND version_id = %s",
                (*scope.scope_key, version_id),
            ).fetchone()
        return _version_from_row(row) if row is not None else None

    def save_version(self, version: AgentDefinitionVersion) -> AgentDefinitionVersion:
        scope = version.scope
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT definition_digest FROM agent_definition_versions"
                " WHERE authority_issuer = %s AND namespace_id = %s"
                " AND definition_id = %s AND version_id = %s",
                (*scope.scope_key, version.version_id),
            ).fetchone()
            if existing is not None:
                if existing["definition_digest"] != version.definition_digest:
                    raise AgentRegistryStorageError(
                        "Version content changed under a reused version_id"
                    )
                return version
            by_number = connection.execute(
                "SELECT version_id, definition_digest FROM agent_definition_versions"
                " WHERE authority_issuer = %s AND namespace_id = %s"
                " AND definition_id = %s AND version = %s",
                (*scope.scope_key, version.version),
            ).fetchone()
            if by_number is not None:
                raise AgentRegistryStorageError(
                    "Definition version number already exists with different content"
                )
            connection.execute(
                """
                INSERT INTO agent_definition_versions (
                    authority_issuer, namespace_id, definition_id, version_id,
                    version, schema_version, model_policy_ref, tool_profile_ref,
                    skill_snapshot_digest, memory_policy_ref, security_policy_ref,
                    evaluation_profile_ref, runtime_profile_ref, definition_digest,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                _version_row_values(version),
            )
        return version

    def resolve_published(
        self,
        scope: AgentDefinitionScope,
        *,
        environment: str,
    ) -> AgentRelease | None:
        with self._database.connect() as connection:
            rows = connection.execute(
                self._release_query() + " AND environment = %s AND status = 'published'",
                (*scope.scope_key, environment),
            ).fetchall()
        published = [row for row in rows if row is not None]
        if not published:
            return None
        if len(published) > 1:
            raise AgentRegistryStorageError(
                "multiple effective Published Releases detected; failing closed"
            )
        return _release_from_row(published[0])

    def append_release(
        self,
        release: AgentRelease,
        *,
        expected_revision: int | None = None,
    ) -> AgentRelease:
        scope_key = (
            release.authority_issuer,
            release.namespace_id,
            release.definition_id,
        )
        with self._database.connect() as connection:
            current = connection.execute(
                "SELECT release_id, revision FROM agent_release_records"
                " WHERE authority_issuer = %s AND namespace_id = %s"
                " AND definition_id = %s AND environment = %s AND status = 'published'",
                (*scope_key, release.environment),
            ).fetchone()
            if (
                release.status is AgentReleaseStatus.PUBLISHED
                and current is not None
                and current["release_id"] != release.release_id
            ):
                superseded = _supersede_current(
                    connection,
                    scope_key,
                    release.environment,
                    current["revision"],
                    release.actor_ref,
                    release.effective_at,
                )
                if superseded is None:
                    raise AgentRegistryStorageError(
                        "current Published Release changed concurrently"
                    )
            existing = connection.execute(
                "SELECT revision, status FROM agent_release_records"
                " WHERE authority_issuer = %s AND namespace_id = %s"
                " AND definition_id = %s AND environment = %s AND release_id = %s",
                (*scope_key, release.environment, release.release_id),
            ).fetchone()
            if existing is not None:
                durable_revision = int(existing["revision"])
                if existing["status"] == release.status.value:
                    if release.revision != durable_revision:
                        raise AgentRegistryStorageError(
                            "Release idempotent replay revision mismatch"
                        )
                    return release
                if release.revision != durable_revision + 1:
                    raise AgentRegistryStorageError(
                        "Release transition revision must increase by one"
                    )
                changed = connection.execute(
                    """
                    UPDATE agent_release_records
                    SET status = %s, reason_class = %s, revision = revision + 1
                    WHERE authority_issuer = %s AND namespace_id = %s
                      AND definition_id = %s AND environment = %s
                      AND release_id = %s AND revision = %s
                    RETURNING release_id
                    """,
                    (
                        release.status.value,
                        release.reason_class,
                        *scope_key,
                        release.environment,
                        release.release_id,
                        durable_revision,
                    ),
                ).fetchone()
                if changed is None:
                    raise AgentRegistryStorageError(
                        "Release transition raced concurrently"
                    )
                return release
            latest = connection.execute(
                "SELECT coalesce(max(revision), 0) AS max_revision"
                " FROM agent_release_records"
                " WHERE authority_issuer = %s AND namespace_id = %s"
                " AND definition_id = %s AND environment = %s",
                (*scope_key, release.environment),
            ).fetchone()
            next_revision = int(latest["max_revision"]) + 1 if latest else 1
            if expected_revision is not None and expected_revision != next_revision - 1:
                raise AgentRegistryStorageError(
                    "Release expected revision does not match durable history"
                )
            if release.status is AgentReleaseStatus.PUBLISHED:
                release = release.model_copy(update={"revision": next_revision})
            connection.execute(
                """
                INSERT INTO agent_release_records (
                    authority_issuer, namespace_id, definition_id, environment,
                    release_id, version_id, status, revision, definition_digest,
                    actor_ref, reason_class, effective_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    *scope_key,
                    release.environment,
                    release.release_id,
                    release.version_id,
                    release.status.value,
                    release.revision,
                    release.definition_digest,
                    release.actor_ref,
                    release.reason_class,
                    release.effective_at,
                ),
            )
        return release

    def record_eval_evidence(self, evidence: AgentDefinitionEvalEvidence) -> None:
        scope_key = (
            evidence.authority_issuer,
            evidence.namespace_id,
            evidence.definition_id,
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_definition_eval_evidence (
                    authority_issuer, namespace_id, definition_id, version_id,
                    evidence_id, definition_digest, binding_purpose, passed,
                    evaluator_actor, case_summary
                ) VALUES (%s, %s, %s, %s, %s, %s, 'eval', %s, %s, %s)
                """,
                (
                    *scope_key,
                    evidence.version_id,
                    evidence.evidence_id,
                    evidence.definition_digest,
                    evidence.passed,
                    evidence.evaluator_actor,
                    _Jsonb(evidence.case_summary),
                ),
            )

    def latest_eval_evidence(
        self,
        scope: AgentDefinitionScope,
        version_id: AgentDefinitionVersionId,
    ) -> AgentDefinitionEvalEvidence | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT version_id, evidence_id, definition_digest, passed,
                       evaluator_actor, case_summary
                FROM agent_definition_eval_evidence
                WHERE authority_issuer = %s AND namespace_id = %s
                  AND definition_id = %s AND version_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (*scope.scope_key, version_id),
            ).fetchone()
        if row is None:
            return None
        return AgentDefinitionEvalEvidence(
            authority_issuer=scope.authority_issuer,
            namespace_id=scope.namespace_id,
            definition_id=scope.definition_id,
            version_id=row["version_id"],
            evidence_id=row["evidence_id"],
            definition_digest=row["definition_digest"],
            passed=bool(row["passed"]),
            evaluator_actor=row["evaluator_actor"],
            case_summary=dict(row["case_summary"]),
        )

    def _definition_query(self) -> str:
        return (
            "SELECT authority_issuer, namespace_id, definition_id, name,"
            " description, revision, created_at"
            " FROM agent_definition_records"
            " WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s"
        )

    def _version_query(self) -> str:
        return (
            "SELECT authority_issuer, namespace_id, definition_id, version_id,"
            " version, schema_version, model_policy_ref,"
            " tool_profile_ref, skill_snapshot_digest, memory_policy_ref,"
            " security_policy_ref, evaluation_profile_ref, runtime_profile_ref,"
            " definition_digest, created_at"
            " FROM agent_definition_versions"
            " WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s"
        )

    def _release_query(self) -> str:
        return (
            "SELECT authority_issuer, namespace_id, definition_id, release_id,"
            " version_id, environment, status, revision, definition_digest,"
            " actor_ref, reason_class, effective_at"
            " FROM agent_release_records"
            " WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s"
        )


def _supersede_current(
    connection: Any,
    scope_key: tuple[str, str, AgentDefinitionId],
    environment: str,
    current_revision: int,
    actor_ref: str,
    effective_at: Any,
) -> Any:
    del actor_ref
    return connection.execute(
        """
        UPDATE agent_release_records
        SET status = 'deprecated', reason_class = 'superseded',
            revision = revision + 1
        WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s
          AND environment = %s AND status = 'published' AND revision = %s
        RETURNING release_id
        """,
        (*scope_key, environment, current_revision),
    ).fetchone()


def _definition_from_row(row: dict[str, Any]) -> AgentDefinition:
    return AgentDefinition(
        definition_id=AgentDefinitionId(row["definition_id"]),
        authority_issuer=row["authority_issuer"],
        namespace_id=row["namespace_id"],
        name=row["name"],
        description=row["description"],
        revision=int(row["revision"]),
        created_at=row["created_at"],
    )


def _version_row_values(version: AgentDefinitionVersion) -> tuple[Any, ...]:
    return (
        version.authority_issuer,
        version.namespace_id,
        version.definition_id,
        version.version_id,
        version.version,
        version.schema_version,
        version.model_policy_ref,
        version.tool_profile_ref,
        version.skill_snapshot_digest,
        version.memory_policy_ref,
        version.security_policy_ref,
        version.evaluation_profile_ref,
        version.runtime_profile_ref,
        version.definition_digest,
        version.created_at,
    )


def _version_from_row(row: dict[str, Any]) -> AgentDefinitionVersion:
    return AgentDefinitionVersion(
        version_id=AgentDefinitionVersionId(row["version_id"]),
        definition_id=AgentDefinitionId(row["definition_id"]),
        authority_issuer=row["authority_issuer"],
        namespace_id=row["namespace_id"],
        version=int(row["version"]),
        schema_version=row["schema_version"],
        model_policy_ref=row["model_policy_ref"],
        tool_profile_ref=row["tool_profile_ref"],
        skill_snapshot_digest=row["skill_snapshot_digest"],
        memory_policy_ref=row["memory_policy_ref"],
        security_policy_ref=row["security_policy_ref"],
        evaluation_profile_ref=row["evaluation_profile_ref"],
        runtime_profile_ref=row["runtime_profile_ref"],
        definition_digest=row["definition_digest"],
        created_at=row["created_at"],
    )


def _release_from_row(row: dict[str, Any]) -> AgentRelease:
    return AgentRelease(
        release_id=AgentReleaseId(row["release_id"]),
        definition_id=AgentDefinitionId(row["definition_id"]),
        version_id=AgentDefinitionVersionId(row["version_id"]),
        authority_issuer=row["authority_issuer"],
        namespace_id=row["namespace_id"],
        environment=row["environment"],
        status=AgentReleaseStatus(row["status"]),
        revision=int(row["revision"]),
        definition_digest=row["definition_digest"],
        actor_ref=row["actor_ref"],
        reason_class=row["reason_class"],
        effective_at=row["effective_at"],
    )
