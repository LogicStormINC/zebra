from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_core.domain.identifiers import SessionId

from agent_storage.artifacts import SessionArtifact, SQLiteArtifactStore
from agent_storage.projections import SQLiteProjectionStore


@dataclass(frozen=True)
class SessionArtifactResolution:
    session_exists: bool
    artifact: SessionArtifact | None


def resolve_session_artifact(
    database_path: str | Path,
    session_id: SessionId,
    artifact_id: str,
) -> SessionArtifactResolution:
    if SQLiteProjectionStore(database_path).get_session(session_id) is None:
        return SessionArtifactResolution(session_exists=False, artifact=None)
    for artifact in SQLiteArtifactStore(database_path).list_for_session(session_id):
        if artifact.artifact_id == artifact_id:
            return SessionArtifactResolution(session_exists=True, artifact=artifact)
    return SessionArtifactResolution(session_exists=True, artifact=None)
