"""Fenced PostgreSQL Context Capsule aggregate."""

from hashlib import sha256
from typing import Any
from uuid import UUID

from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.contracts.events import ContextCapsuleCreatedPayload
from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    validate_context_capsule,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, SessionId, new_artifact_id
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports.aggregate_mutation import (
    AdministrativeMutationCAS,
    WorkerMutationAuthority,
)
from agent_core.ports.context_lifecycle_store import (
    ContextLifecycleCommitResult,
    ContextLifecycleStorePort,
    StoredContextCapsule,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.projections import (
    get_session_in_transaction,
    save_session_in_transaction,
)
from agent_storage.postgres.workspaces import (
    get_workspace_in_transaction,
    save_workspace_in_transaction,
)


class PostgresContextLifecycleConflictError(ValueError):
    """Raised when the immutable capsule or active-pointer CAS conflicts."""


class PostgresContextLifecycleStore(ContextLifecycleStorePort):
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def commit_worker_compaction(
        self,
        *,
        authority: WorkerMutationAuthority,
        session: Session,
        workspace: WorkspaceProjection,
        capsule: ContextCapsule,
        validation_context: ContextCapsuleValidationContext,
        expected_active_capsule_id: str | None,
        compaction_event: SessionEvent,
    ) -> ContextLifecycleCommitResult:
        self._validate_worker(authority, session, workspace, compaction_event)
        validate_context_capsule(capsule, validation_context)
        if capsule.source_event_range is None:
            raise ValueError("an active context capsule requires a source event range")
        if compaction_event.event_type is not EventType.CONTEXT_COMPACTED:
            raise ValueError("worker context aggregate requires context_compacted")
        capsule_event = self._capsule_event(capsule, compaction_event, expected_active_capsule_id)
        with self._database.connect() as connection:
            assert_current_lease_fence(
                connection,
                self._database.deployment_namespace,
                authority.session_id,
                authority.lease_fence,
            )
            existing = self._stored_capsule(connection, capsule.capsule_id)
            if existing is not None:
                return self._retry_result(
                    connection, existing, compaction_event, session, workspace
                )
            self._require_pointer(connection, session.session_id, expected_active_capsule_id)
            canonical_compaction = append_event_in_transaction(
                connection, self._database.deployment_namespace, compaction_event
            )
            if canonical_compaction.sequence != authority.expected_stream_revision + 1:
                raise PostgresContextLifecycleConflictError("compaction stream revision changed")
            self._insert_capsule(connection, capsule, canonical_compaction, capsule_event)
            canonical_capsule = append_event_in_transaction(
                connection, self._database.deployment_namespace, capsule_event
            )
            self._advance_pointer(
                connection, session.session_id, capsule, capsule_event, expected_active_capsule_id
            )
            stored_session, stored_workspace = self._save_projections(
                connection, session, workspace, canonical_compaction, canonical_capsule
            )
        stored = StoredContextCapsule(
            artifact_id=ArtifactId(UUID(str(capsule_event.payload["artifact_id"]))),
            session_id=session.session_id,
            capsule=capsule,
            payload_sha256=_payload_sha(capsule),
            event=canonical_capsule,
            compaction_event=canonical_compaction,
        )
        return ContextLifecycleCommitResult(
            stored, canonical_compaction, stored_session, stored_workspace
        )

    def commit_administrative_activation(
        self,
        *,
        authority: AdministrativeMutationCAS,
        session: Session,
        workspace: WorkspaceProjection,
        capsule_id: str,
        expected_active_capsule_id: str | None,
        event: SessionEvent,
    ) -> ContextLifecycleCommitResult:
        self._validate_administrator(authority, session, workspace, event)
        with self._database.connect() as connection:
            stored = self._stored_capsule(connection, capsule_id)
            if stored is None or stored.session_id != session.session_id:
                raise KeyError("context capsule is unavailable for this session")
            self._require_pointer(connection, session.session_id, expected_active_capsule_id)
            canonical = append_event_in_transaction(
                connection, self._database.deployment_namespace, event
            )
            if canonical.sequence != authority.expected_stream_revision + 1:
                raise PostgresContextLifecycleConflictError(
                    "administrative stream revision changed"
                )
            self._advance_pointer(
                connection,
                session.session_id,
                stored.capsule,
                stored.event,
                expected_active_capsule_id,
                event_sequence=canonical.sequence,
            )
            stored_session, stored_workspace = self._save_projections(
                connection, session, workspace, canonical
            )
        return ContextLifecycleCommitResult(stored, canonical, stored_session, stored_workspace)

    def persist_capsule_and_advance(self, **_: object) -> StoredContextCapsule:
        raise NotImplementedError("PostgreSQL Context writes require explicit mutation authority")

    def activate_capsule(self, **_: object) -> StoredContextCapsule:
        raise NotImplementedError("PostgreSQL Context activation requires administrative CAS")

    def get_capsule(self, capsule_id: str) -> StoredContextCapsule | None:
        with self._database.connect() as connection:
            return self._stored_capsule(connection, capsule_id)

    def get_active_capsule(self, session_id: SessionId) -> StoredContextCapsule | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT capsule_id FROM active_context_projections
                WHERE deployment_namespace = %s AND session_id = %s
                """,
                (self._database.deployment_namespace, session_id),
            ).fetchone()
            return None if row is None else self._stored_capsule(connection, row["capsule_id"])

    def _validate_worker(
        self,
        authority: WorkerMutationAuthority,
        session: Session,
        workspace: WorkspaceProjection,
        event: SessionEvent,
    ) -> None:
        if authority.deployment_namespace != self._database.deployment_namespace:
            raise LeaseLostError("context mutation authority belongs to another namespace")
        if (
            authority.session_id != event.session_id
            or session.session_id != event.session_id
            or workspace.session_id != event.session_id
        ):
            raise LeaseLostError("context mutation authority belongs to another session")
        if event.sequence != authority.expected_stream_revision + 1:
            raise PostgresContextLifecycleConflictError(
                "context Event does not follow expected revision"
            )

    def _validate_administrator(
        self,
        authority: AdministrativeMutationCAS,
        session: Session,
        workspace: WorkspaceProjection,
        event: SessionEvent,
    ) -> None:
        if (
            authority.deployment_namespace != self._database.deployment_namespace
            or authority.session_id != event.session_id
        ):
            raise PostgresContextLifecycleConflictError(
                "administrative CAS scope does not match Context Event"
            )
        if (
            session.session_id != event.session_id
            or workspace.session_id != event.session_id
            or event.sequence != authority.expected_stream_revision + 1
        ):
            raise PostgresContextLifecycleConflictError(
                "administrative Context projection revision changed"
            )

    def _capsule_event(
        self, capsule: ContextCapsule, compaction: SessionEvent, previous: str | None
    ) -> SessionEvent:
        assert capsule.source_event_range is not None
        artifact_id = new_artifact_id()
        return SessionEvent.create(
            session_id=compaction.session_id,
            sequence=compaction.sequence + 1,
            event_type=EventType.CONTEXT_CAPSULE_CREATED,
            actor=EventActor.SYSTEM,
            payload=ContextCapsuleCreatedPayload(
                capsule_id=capsule.capsule_id,
                artifact_id=str(artifact_id),
                schema_version=capsule.version,
                source_hash=capsule.source_hash,
                source_event_range=capsule.source_event_range,
                previous_capsule_id=previous,
            ).model_dump(mode="json"),
            idempotency_key=f"context-capsule:{capsule.capsule_id}",
            model_profile=capsule.model_profile,
            created_at=compaction.created_at,
        )

    def _stored_capsule(self, connection: Any, capsule_id: str) -> StoredContextCapsule | None:
        row = connection.execute(
            """
            SELECT * FROM context_capsule_artifacts
            WHERE deployment_namespace = %s AND capsule_id = %s
            """,
            (self._database.deployment_namespace, capsule_id),
        ).fetchone()
        if row is None:
            return None
        capsule = ContextCapsule.model_validate(row["payload"])
        if _payload_sha(capsule) != row["payload_sha256"]:
            raise PostgresContextLifecycleConflictError("context capsule payload checksum failed")
        event = self._event(connection, row["capsule_event_id"])
        compaction = self._event(connection, row["compaction_event_id"])
        return StoredContextCapsule(
            ArtifactId(row["artifact_id"]),
            SessionId(row["session_id"]),
            capsule,
            row["payload_sha256"],
            event,
            compaction,
        )

    def _event(self, connection: Any, event_id: UUID) -> SessionEvent:
        row = connection.execute(
            """
            SELECT event_id, session_id, sequence, event_type, payload, actor,
                   created_at, causation_id, correlation_id, idempotency_key,
                   policy_version, model_profile
            FROM session_events
            WHERE deployment_namespace = %s AND event_id = %s
            """,
            (self._database.deployment_namespace, event_id),
        ).fetchone()
        if row is None:
            raise PostgresContextLifecycleConflictError("context lifecycle Event is missing")
        return SessionEvent.model_validate(row)

    def _retry_result(
        self,
        connection: Any,
        stored: StoredContextCapsule,
        compaction: SessionEvent,
        session: Session,
        workspace: WorkspaceProjection,
    ) -> ContextLifecycleCommitResult:
        if stored.compaction_event is None or not _same_event(stored.compaction_event, compaction):
            raise PostgresContextLifecycleConflictError(
                "capsule id belongs to a different compaction"
            )
        self._require_pointer(connection, session.session_id, stored.capsule.capsule_id)
        saved_session = get_session_in_transaction(
            connection, self._database.deployment_namespace, session.session_id
        )
        saved_workspace = get_workspace_in_transaction(
            connection, self._database.deployment_namespace, session.session_id
        )
        if (
            saved_session is None
            or saved_workspace is None
            or saved_session.current_sequence != stored.event.sequence
            or saved_workspace.current_sequence != stored.event.sequence
        ):
            raise PostgresContextLifecycleConflictError(
                "canonical Context projections are incomplete"
            )
        return ContextLifecycleCommitResult(
            stored, stored.compaction_event, saved_session, saved_workspace
        )

    def _require_pointer(
        self, connection: Any, session_id: SessionId, expected: str | None
    ) -> None:
        row = connection.execute(
            """
            SELECT capsule_id FROM active_context_projections
            WHERE deployment_namespace = %s AND session_id = %s
            FOR UPDATE
            """,
            (self._database.deployment_namespace, session_id),
        ).fetchone()
        actual = None if row is None else row["capsule_id"]
        if actual != expected:
            raise PostgresContextLifecycleConflictError("active Context capsule changed")

    def _insert_capsule(
        self,
        connection: Any,
        capsule: ContextCapsule,
        compaction: SessionEvent,
        created: SessionEvent,
    ) -> None:
        connection.execute(
            """
            INSERT INTO context_capsule_artifacts (
                deployment_namespace, capsule_id, artifact_id, session_id, payload,
                payload_sha256, source_hash, compaction_event_id, capsule_event_id,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                self._database.deployment_namespace,
                capsule.capsule_id,
                created.payload["artifact_id"],
                compaction.session_id,
                Jsonb(capsule.model_dump(mode="json")),
                _payload_sha(capsule),
                capsule.source_hash,
                compaction.event_id,
                created.event_id,
                created.created_at,
            ),
        )

    def _advance_pointer(
        self,
        connection: Any,
        session_id: SessionId,
        capsule: ContextCapsule,
        created: SessionEvent,
        expected: str | None,
        *,
        event_sequence: int | None = None,
    ) -> None:
        artifact_id = created.payload.get("artifact_id")
        if not isinstance(artifact_id, str):
            raise PostgresContextLifecycleConflictError("Context capsule Event is malformed")
        sequence = created.sequence if event_sequence is None else event_sequence
        if expected is None:
            result = connection.execute(
                """
                INSERT INTO active_context_projections (
                    deployment_namespace, session_id, capsule_id, artifact_id,
                    source_hash, event_sequence, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    self._database.deployment_namespace,
                    session_id,
                    capsule.capsule_id,
                    artifact_id,
                    capsule.source_hash,
                    sequence,
                    created.created_at,
                ),
            )
        else:
            result = connection.execute(
                """
                UPDATE active_context_projections
                SET capsule_id = %s, artifact_id = %s, source_hash = %s,
                    event_sequence = %s, updated_at = %s
                WHERE deployment_namespace = %s AND session_id = %s AND capsule_id = %s
                """,
                (
                    capsule.capsule_id,
                    artifact_id,
                    capsule.source_hash,
                    sequence,
                    created.created_at,
                    self._database.deployment_namespace,
                    session_id,
                    expected,
                ),
            )
        if result.rowcount != 1:
            raise PostgresContextLifecycleConflictError("active Context capsule CAS failed")

    def _save_projections(
        self,
        connection: Any,
        session: Session,
        workspace: WorkspaceProjection,
        *events: SessionEvent,
    ) -> tuple[Session, WorkspaceProjection]:
        projected_session, projected_workspace = session, workspace
        for event in events:
            projected_session = apply_session_event(projected_session, event)
            projected_workspace = apply_workspace_event(projected_workspace, event)
        return (
            save_session_in_transaction(
                connection, self._database.deployment_namespace, projected_session
            ),
            save_workspace_in_transaction(
                connection, self._database.deployment_namespace, projected_workspace
            ),
        )


def _payload_sha(capsule: ContextCapsule) -> str:
    return sha256(capsule.model_dump_json().encode()).hexdigest()


def _same_event(left: SessionEvent, right: SessionEvent) -> bool:
    return (
        left.sequence == right.sequence
        and left.event_type is right.event_type
        and left.actor is right.actor
        and left.payload == right.payload
    )
