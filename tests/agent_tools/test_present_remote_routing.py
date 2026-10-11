"""Remote references must not trigger an artifact download/repair loop."""

from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall
from agent_tools.builtin.present import ContentPresentTool, content_present_contract
from agent_tools.errors import ToolArgumentError


class NoArtifactReader:
    def describe_payload(self, *args):
        raise AssertionError("remote URLs must not be looked up as artifacts")


@pytest.mark.parametrize("kind", ["image", "video", "chart", "file"])
@pytest.mark.parametrize("url", ["https://example.com/a.png", "https://example.com/" + "a" * 200])
def test_remote_artifact_argument_returns_actionable_routing(kind, url):
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="content.present",
        arguments={"parts": [{"type": kind, "artifact_uri": url, "alt": "Example"}]},
        created_at=datetime.now(UTC),
    )
    with pytest.raises(ToolArgumentError, match="do not download.*external_video"):
        ContentPresentTool(NoArtifactReader(), new_session_id()).handle(call)


def test_contract_distinguishes_host_images_and_artifact_presentation():
    description = content_present_contract.description
    assert "![alt](exact_image_url)" in description
    assert "download failures do not prove" in description
    assert "external_video" in description
