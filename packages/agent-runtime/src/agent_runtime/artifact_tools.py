from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.ports import ArtifactPayloadReadPort
from agent_tools import ArtifactReadTool, ContentPresentTool


def build_artifact_read_tools(
    reader: ArtifactPayloadReadPort | None,
    session_id: str | None,
) -> tuple[ArtifactReadTool | ContentPresentTool, ...]:
    if reader is None or session_id is None:
        return ()
    scoped_session_id = SessionId(UUID(session_id))
    return (
        ArtifactReadTool(reader, scoped_session_id),
        ContentPresentTool(reader, scoped_session_id),
    )
