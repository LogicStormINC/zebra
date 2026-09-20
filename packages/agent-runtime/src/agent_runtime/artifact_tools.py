from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.ports import ArtifactPayloadReadPort
from agent_tools import ArtifactReadTool


def build_artifact_read_tools(
    reader: ArtifactPayloadReadPort | None,
    session_id: str | None,
) -> tuple[ArtifactReadTool, ...]:
    if reader is None or session_id is None:
        return ()
    return (ArtifactReadTool(reader, SessionId(UUID(session_id))),)
