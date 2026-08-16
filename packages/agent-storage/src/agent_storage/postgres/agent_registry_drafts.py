"""PostgreSQL draft authority for the Agent Definition Registry (v19)."""

from __future__ import annotations

from typing import Any

from agent_core.domain.agent_definition_drafts import (
    AgentDefinitionDraft,
    AgentDefinitionDraftValidation,
    AgentDraftValidationIssue,
    AgentDraftValidationStatus,
)
from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_core.domain.identifiers import AgentDefinitionId

from agent_storage.postgres.agent_registry_common import (
    AgentRegistryStorageError,
    _Jsonb,
)
from agent_storage.postgres.database import PostgresDatabase


class AgentDraftAuthorityMixin:
    """Mutable draft + append-only validation evidence under one Definition."""

    _database: PostgresDatabase

    def get_draft(self, scope: AgentDefinitionScope) -> AgentDefinitionDraft | None:
        with self._database.connect() as connection:
            row = connection.execute(
                self._draft_query(),
                scope.scope_key,
            ).fetchone()
        return _draft_from_row(row) if row is not None else None

    def save_draft(
        self,
        draft: AgentDefinitionDraft,
        *,
        expected_revision: int | None = None,
    ) -> AgentDefinitionDraft:
        scope = draft.scope
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT revision FROM agent_definition_drafts"
                " WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s",
                scope.scope_key,
            ).fetchone()
            if existing is None:
                if expected_revision is not None:
                    raise AgentRegistryStorageError(
                        "cannot create a Draft with an expected revision"
                    )
                connection.execute(
                    """
                    INSERT INTO agent_definition_drafts (
                        authority_issuer, namespace_id, definition_id, name,
                        description, model_policy_ref, tool_profile_ref,
                        skill_snapshot_digest, memory_policy_ref, security_policy_ref,
                        evaluation_profile_ref, runtime_profile_ref, revision, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    _draft_row_values(draft),
                )
                return draft
            current = int(existing["revision"])
            if expected_revision is None or expected_revision != current:
                raise AgentRegistryStorageError(
                    f"Draft revision conflict: durable revision is {current}"
                )
            if draft.revision != current + 1:
                raise AgentRegistryStorageError(
                    "Draft revision must increase by one over the durable row"
                )
            changed = connection.execute(
                """
                UPDATE agent_definition_drafts
                SET name = %s, description = %s, model_policy_ref = %s,
                    tool_profile_ref = %s, skill_snapshot_digest = %s,
                    memory_policy_ref = %s, security_policy_ref = %s,
                    evaluation_profile_ref = %s, runtime_profile_ref = %s,
                    revision = %s, updated_at = %s
                WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s
                  AND revision = %s
                RETURNING revision
                """,
                (
                    draft.name,
                    draft.description,
                    draft.model_policy_ref,
                    draft.tool_profile_ref,
                    draft.skill_snapshot_digest,
                    draft.memory_policy_ref,
                    draft.security_policy_ref,
                    draft.evaluation_profile_ref,
                    draft.runtime_profile_ref,
                    draft.revision,
                    draft.updated_at,
                    *scope.scope_key,
                    current,
                ),
            ).fetchone()
            if changed is None:
                raise AgentRegistryStorageError(
                    "Draft revision changed concurrently; retry from durable state"
                )
            return draft

    def append_draft_validation(
        self, validation: AgentDefinitionDraftValidation
    ) -> None:
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM agent_definition_draft_validations"
                " WHERE authority_issuer = %s AND namespace_id = %s"
                " AND definition_id = %s AND validation_id = %s",
                (*validation.scope.scope_key, validation.validation_id),
            ).fetchone()
            if existing is not None:
                return
            connection.execute(
                """
                INSERT INTO agent_definition_draft_validations (
                    authority_issuer, namespace_id, definition_id, validation_id,
                    draft_revision, status, issues, evaluated_at, evaluator_actor
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    *validation.scope.scope_key,
                    validation.validation_id,
                    validation.draft_revision,
                    validation.status.value,
                    _Jsonb([issue.model_dump() for issue in validation.issues]),
                    validation.evaluated_at,
                    validation.evaluator_actor,
                ),
            )

    def latest_draft_validation(
        self, scope: AgentDefinitionScope
    ) -> AgentDefinitionDraftValidation | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT authority_issuer, namespace_id, definition_id, validation_id,
                       draft_revision, status, issues, evaluated_at, evaluator_actor
                FROM agent_definition_draft_validations
                WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                scope.scope_key,
            ).fetchone()
        return _draft_validation_from_row(row) if row is not None else None

    def _draft_query(self) -> str:
        return (
            "SELECT authority_issuer, namespace_id, definition_id, name,"
            " description, model_policy_ref, tool_profile_ref, skill_snapshot_digest,"
            " memory_policy_ref, security_policy_ref, evaluation_profile_ref,"
            " runtime_profile_ref, revision, updated_at"
            " FROM agent_definition_drafts"
            " WHERE authority_issuer = %s AND namespace_id = %s AND definition_id = %s"
        )


def _draft_row_values(draft: AgentDefinitionDraft) -> tuple[Any, ...]:
    return (
        draft.authority_issuer,
        draft.namespace_id,
        draft.definition_id,
        draft.name,
        draft.description,
        draft.model_policy_ref,
        draft.tool_profile_ref,
        draft.skill_snapshot_digest,
        draft.memory_policy_ref,
        draft.security_policy_ref,
        draft.evaluation_profile_ref,
        draft.runtime_profile_ref,
        draft.revision,
        draft.updated_at,
    )


def _draft_from_row(row: dict[str, Any]) -> AgentDefinitionDraft:
    return AgentDefinitionDraft(
        authority_issuer=row["authority_issuer"],
        namespace_id=row["namespace_id"],
        definition_id=AgentDefinitionId(row["definition_id"]),
        name=row["name"],
        description=row["description"],
        model_policy_ref=row["model_policy_ref"],
        tool_profile_ref=row["tool_profile_ref"],
        skill_snapshot_digest=row["skill_snapshot_digest"],
        memory_policy_ref=row["memory_policy_ref"],
        security_policy_ref=row["security_policy_ref"],
        evaluation_profile_ref=row["evaluation_profile_ref"],
        runtime_profile_ref=row["runtime_profile_ref"],
        revision=int(row["revision"]),
        updated_at=row["updated_at"],
    )


def _draft_validation_from_row(
    row: dict[str, Any],
) -> AgentDefinitionDraftValidation:
    return AgentDefinitionDraftValidation(
        authority_issuer=row["authority_issuer"],
        namespace_id=row["namespace_id"],
        definition_id=AgentDefinitionId(row["definition_id"]),
        validation_id=row["validation_id"],
        draft_revision=int(row["draft_revision"]),
        status=AgentDraftValidationStatus(row["status"]),
        issues=tuple(
            AgentDraftValidationIssue(**issue) for issue in row["issues"]
        ),
        evaluated_at=row["evaluated_at"],
        evaluator_actor=row["evaluator_actor"],
    )
