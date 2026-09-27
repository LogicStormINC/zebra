from agent_core.domain.identifiers import SessionId, new_session_id
from agent_core.ports import ArtifactPayloadReadInspection
from agent_runtime.artifact_tools import build_artifact_read_tools


class ArtifactReader:
    def describe_payload(
        self, session_id: SessionId, uri: str
    ) -> ArtifactPayloadReadInspection | None:
        return None

    def inspect_payload(
        self, session_id: SessionId, uri: str
    ) -> ArtifactPayloadReadInspection | None:
        return None

    def read_payload_bytes(self, session_id: SessionId, uri: str) -> bytes:
        return b""

    def read_payload_range(self, session_id: SessionId, uri: str, start: int, end: int) -> bytes:
        return b""


def test_artifact_tools_include_read_and_presentation_when_authority_is_available() -> None:
    session_id = new_session_id()

    tools = build_artifact_read_tools(ArtifactReader(), str(session_id))

    assert [tool.contract.name for tool in tools] == ["artifacts.read", "content.present"]


def test_artifact_tools_require_reader_and_current_session() -> None:
    assert build_artifact_read_tools(None, str(new_session_id())) == ()
    assert build_artifact_read_tools(ArtifactReader(), None) == ()
