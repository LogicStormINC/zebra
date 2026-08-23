"""Local tool-output artifact projection composition."""

from datetime import UTC, datetime
from uuid import UUID

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import SessionId
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_tools import ToolOutputProjector


def build_output_projector(
    store: ArtifactPayloadStorePort | None,
    *,
    current_session_id: str | None,
) -> ToolOutputProjector | None:
    if store is None:
        return None
    if current_session_id is None:
        raise ValueError("artifact output projection requires current_session_id")
    try:
        session_id = SessionId(UUID(current_session_id))
    except ValueError as exc:
        raise ValueError("current_session_id must be a UUID") from exc

    def persist(content: str, file_name: str) -> str:
        stored = store.store_payload(
            ArtifactPayloadWrite(
                session_id=session_id,
                kind="tool_output",
                mime_type="text/plain",
                payload=content.encode("utf-8"),
                file_name=file_name,
                created_at=datetime.now(UTC),
            )
        )
        return stored.uri

    return ToolOutputProjector(persist)
