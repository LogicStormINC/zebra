"""Per-frame plugin authority failures survive transport credential sanitization."""

import pytest
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_runtime.mcp_http import McpHttpSession
from agent_runtime.mcp_http_authorization import resolve_bearer_header
from agent_runtime.mcp_sse import McpSseSession

from tests.agent_runtime.test_mcp_http_streaming import Server


def unavailable(*args):
    raise PluginAuthorityUnavailable("accepted plugin authority is unavailable")


@pytest.mark.parametrize("surface", ["anonymous", "bearer", "sse"])
def test_typed_plugin_stop_survives_each_frame_authorization_surface(surface: str) -> None:
    with pytest.raises(PluginAuthorityUnavailable):
        if surface == "bearer":
            resolve_bearer_header(unavailable, Server().url, {"method": "tools/call"})
        elif surface == "anonymous":
            McpHttpSession(Server(), 1, frame_authorizer=unavailable)._send_frame(
                {"method": "tools/call"}
            )
        else:
            McpSseSession(Server(), 1, frame_authorizer=unavailable)._headers(
                {"method": "tools/call"}
            )
