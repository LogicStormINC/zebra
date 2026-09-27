from datetime import UTC, datetime
from uuid import UUID

import pytest
from agent_core.domain.identifiers import ArtifactId, SessionId, new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.ports import ArtifactPayloadReadInspection, ArtifactPayloadReadStatus
from agent_tools.builtin.present import ContentPresentTool
from agent_tools.errors import ToolArgumentError


class PresentationReader:
    def __init__(
        self,
        session_id: SessionId,
        artifacts: dict[str, tuple[str, str]],
        *,
        authority_session_id: SessionId | None = None,
    ) -> None:
        self.session_id = session_id
        self.authority_session_id = authority_session_id or session_id
        self.artifacts = artifacts

    def describe_payload(
        self, session_id: SessionId, uri: str
    ) -> ArtifactPayloadReadInspection | None:
        if session_id != self.session_id or uri not in self.artifacts:
            return None
        mime_type, file_name = self.artifacts[uri]
        return ArtifactPayloadReadInspection(
            artifact_id=ArtifactId(UUID(uri.removeprefix("artifact://"))),
            session_id=self.authority_session_id,
            mime_type=mime_type,
            file_name=file_name,
            size_bytes=123,
            status=ArtifactPayloadReadStatus.AVAILABLE,
            lifecycle_status="active",
        )

    def inspect_payload(self, session_id: SessionId, uri: str):
        return self.describe_payload(session_id, uri)

    def read_payload_bytes(self, _session_id: SessionId, _uri: str) -> bytes:
        raise AssertionError("presentation must not load Artifact bytes")

    def read_payload_range(
        self, _session_id: SessionId, _uri: str, _start: int, _end: int
    ) -> bytes:
        raise AssertionError("presentation must not load Artifact bytes")


def _uri(number: int) -> str:
    return f"artifact://00000000-0000-4000-8000-{number:012d}"


def _call(parts: list[dict[str, object]]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="content.present",
        arguments={"parts": parts},
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
    )


def test_present_builds_ordered_image_video_chart_and_file_parts() -> None:
    session_id = new_session_id()
    artifacts = {
        _uri(1): ("image/png", "evidence.png"),
        _uri(2): ("video/mp4", "walkthrough.mp4"),
        _uri(3): ("image/jpeg", "poster.jpg"),
        _uri(4): ("application/vnd.vegalite.v6+json", "trend.vl.json"),
        _uri(5): ("text/csv", "trend.csv"),
        _uri(6): ("application/pdf", "report.pdf"),
    }
    result = ContentPresentTool(PresentationReader(session_id, artifacts), session_id).handle(
        _call(
            [
                {"type": "image", "artifact_uri": _uri(1), "alt": "Evidence image"},
                {
                    "type": "video",
                    "artifact_uri": _uri(2),
                    "poster_artifact_uri": _uri(3),
                    "title": "Walkthrough",
                },
                {
                    "type": "chart",
                    "artifact_uri": _uri(4),
                    "data_artifact_uri": _uri(5),
                    "title": "Trend",
                    "description": "Daily values",
                },
                {"type": "file", "artifact_uri": _uri(6), "description": "Full report"},
            ]
        )
    )

    assert result.status is ToolCallStatus.EXECUTED
    parts = result.metadata["content_parts"]
    assert isinstance(parts, list)
    assert [part["type"] for part in parts] == ["image", "video", "chart", "file"]
    assert parts[0]["alt"] == "Evidence image"
    assert parts[1]["posterArtifactId"] == _uri(3).removeprefix("artifact://")
    assert parts[2]["dataArtifactId"] == _uri(5).removeprefix("artifact://")
    assert parts[3]["name"] == "report.pdf"
    assert len({part["id"] for part in parts}) == 4


def test_present_rejects_cross_session_or_missing_artifact_authority() -> None:
    session_id = new_session_id()
    tool = ContentPresentTool(
        PresentationReader(
            session_id,
            {_uri(1): ("image/png", "evidence.png")},
            authority_session_id=new_session_id(),
        ),
        session_id,
    )

    result = tool.handle(_call([{"type": "image", "artifact_uri": _uri(1), "alt": "x"}]))

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "artifact_unavailable"
    assert "current session" in result.metadata["detail"]


@pytest.mark.parametrize(
    "parts, message",
    (
        (
            [{"type": "image", "artifact_uri": "https://example.test/a.png", "alt": "x"}],
            "canonical",
        ),
        ([{"type": "image", "artifact_uri": _uri(1)}], "alt"),
        ([{"type": "audio", "artifact_uri": _uri(1)}], "type"),
        ([], "1 to 8"),
    ),
)
def test_present_rejects_untyped_or_remote_content(
    parts: list[dict[str, object]], message: str
) -> None:
    session_id = new_session_id()
    tool = ContentPresentTool(
        PresentationReader(session_id, {_uri(1): ("image/png", "evidence.png")}),
        session_id,
    )

    with pytest.raises(ToolArgumentError, match=message):
        tool.handle(_call(parts))


def test_present_rejects_mime_mismatch_without_reading_payload() -> None:
    session_id = new_session_id()
    tool = ContentPresentTool(
        PresentationReader(session_id, {_uri(1): ("text/html", "unsafe.html")}), session_id
    )

    result = tool.handle(_call([{"type": "image", "artifact_uri": _uri(1), "alt": "x"}]))

    assert result.status is ToolCallStatus.FAILED
    assert "unsupported MIME" in result.metadata["detail"]
