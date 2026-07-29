"""Namespace-scoped Artifact reads from replayable Model/Tool projections."""

from dataclasses import replace
from uuid import UUID

from agent_core.domain.identifiers import EventId, SessionId
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.session_artifact_read import SessionArtifact, SessionArtifactReadPort

from agent_storage.artifacts import compose_session_artifacts
from agent_storage.postgres.database import PostgresDatabase


class PostgresSessionArtifactReadStore(SessionArtifactReadPort):
    """Compose Artifact views without introducing another authority table."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

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
