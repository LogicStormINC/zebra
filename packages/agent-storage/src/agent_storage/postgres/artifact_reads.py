"""Namespace-scoped Artifact reads from replayable Model/Tool projections."""

from dataclasses import replace
from uuid import UUID

from agent_core.domain.identifiers import EventId, SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.session_artifact_read import (
    MAX_ARTIFACT_PROJECTION_BYTES,
    SessionArtifact,
    SessionArtifactReadPort,
    SessionArtifactReadUnavailableError,
    parse_session_artifact_id,
)

from agent_storage.artifacts import _MODEL_TEXT_FIELDS, _TOOL_TEXT_FIELDS, compose_session_artifacts
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_io import TaskIoConnections


class PostgresSessionArtifactReadStore(SessionArtifactReadPort):
    """Compose Artifact views without introducing another authority table."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        task_io_connections: TaskIoConnections | None = None,
    ) -> None:
        self._database = PostgresDatabase(
            dsn,
            deployment_namespace=deployment_namespace,
            task_io_connections=task_io_connections,
        )

    def get_for_session(self, session_id: SessionId, artifact_id: str) -> SessionArtifact | None:
        from agent_storage.artifact_object_reads import artifact_read_scope
        from agent_storage.postgres.task_io import task_io_deadline

        key = parse_session_artifact_id(artifact_id)
        if key is None:
            return None
        namespace = self._database.deployment_namespace
        source = "tool-run" if isinstance(key, UUID) else key[0]
        table = "model_call_projections" if source == "model-call" else "tool_run_projections"
        text_fields = _MODEL_TEXT_FIELDS if source == "model-call" else _TOOL_TEXT_FIELDS
        size = "512 + " + " + ".join(
            f"coalesce(octet_length(p.{field}::text), 0)" for field in text_fields
        )
        join = ""
        where = "p.deployment_namespace = %s AND p.session_id = %s AND p.sequence = %s"
        parameters: tuple[object, ...] = (
            MAX_ARTIFACT_PROJECTION_BYTES,
            namespace,
            session_id,
            key if isinstance(key, UUID) else key[1],
        )
        if isinstance(key, UUID):
            # The existing payload PK binds the UUID to its exact canonical Event,
            # not the first unrelated projection which happens to reuse its URI.
            join = """JOIN artifact_payload_metadata m
                ON p.deployment_namespace = m.deployment_namespace
                AND p.session_id = m.session_id AND p.sequence = m.event_sequence
                AND p.event_id = m.event_id AND p.artifact_uri = m.artifact_uri"""
            where = "m.deployment_namespace = %s AND m.session_id = %s AND m.artifact_id = %s"
        with artifact_read_scope() as scope, task_io_deadline(scope.deadline):
            with self._database.connect() as connection:
                row = connection.execute(
                    f"""SELECT p.event_id, CASE WHEN {size} <= %s THEN
                        to_jsonb(p) - 'deployment_namespace' - 'event_id' END AS record
                        FROM {table} p {join} WHERE {where}""",
                    parameters,
                ).fetchone()
            if row is None:
                return None
            if row["record"] is None:
                raise SessionArtifactReadUnavailableError(
                    "Artifact projection exceeds its byte bound"
                )
            record = row["record"]
            artifact = compose_session_artifacts(
                [ModelCallRecord.model_validate(record)] if source == "model-call" else [],
                [ToolRunRecord.model_validate(record)] if source == "tool-run" else [],
            )[0]
            return replace(artifact, source_event_id=EventId(UUID(str(row["event_id"]))))

    def list_for_session(self, session_id: SessionId) -> list[SessionArtifact]:
        namespace = self._database.deployment_namespace
        with self._database.connect() as connection:
            rows = connection.execute(
                _ARTIFACT_INDEX_SELECT,
                (namespace, session_id, namespace, session_id),
            ).fetchall()
        artifacts = compose_session_artifacts(
            (
                ModelCallRecord.model_validate(row["record"])
                for row in rows
                if row["source"] == "model_call"
            ),
            (
                ToolRunRecord.model_validate(row["record"])
                for row in rows
                if row["source"] == "tool_run"
            ),
        )
        event_ids = {
            (row["source"], int(row["record"]["sequence"])): EventId(UUID(str(row["event_id"])))
            for row in rows
        }
        return [
            replace(
                artifact,
                source_event_id=event_ids[(artifact.source, artifact.sequence)],
            )
            for artifact in artifacts
        ]


_ARTIFACT_INDEX_SELECT = """
SELECT 'model_call' AS source, event_id,
       to_jsonb(model_call_projections) - 'deployment_namespace' - 'event_id' AS record
FROM model_call_projections
WHERE deployment_namespace = %s AND session_id = %s
UNION ALL
SELECT 'tool_run' AS source, event_id,
       to_jsonb(tool_run_projections) - 'deployment_namespace' - 'event_id' AS record
FROM tool_run_projections
WHERE deployment_namespace = %s AND session_id = %s
"""
