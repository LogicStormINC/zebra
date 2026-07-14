import json
from pathlib import Path

import httpx
import pytest
from agent_integrations import MiniMaxImageMcpTransport, build_minimax_image_mcp_transport
from agent_tools.errors import McpProxyTransportError
from agent_tools.mcp_proxy import McpProxyRequest, McpToolTarget
from zebra_agent_config import MiniMaxVisionSettings, ZebraAgentSettings, load_settings


def test_minimax_transport_sends_workspace_image_and_returns_evidence(tmp_path: Path) -> None:
    image = tmp_path / "material-1.png"
    image.write_bytes(b"png-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        body = json.loads(request.content)
        assert body["prompt"] == "Extract visible trades only."
        assert body["image_url"].startswith("data:image/png;base64,")
        return httpx.Response(200, json={"content": "BUY 600036 100 shares"})

    transport = MiniMaxImageMcpTransport(
        workspace_root=tmp_path,
        api_key="secret",
        api_host="https://api.minimaxi.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = transport.execute(_request("material-1.png"))

    assert response.output == "BUY 600036 100 shares"
    assert response.metadata["billable_tool_calls"] == 1
    assert response.metadata["source_file"] == "material-1.png"
    assert len(str(response.metadata["source_sha256"])) == 64


@pytest.mark.parametrize(
    "image_source",
    ["https://example.test/image.png", "data:image/png;base64,AAAA", "../outside.png"],
)
def test_minimax_transport_rejects_non_workspace_sources(
    tmp_path: Path,
    image_source: str,
) -> None:
    (tmp_path.parent / "outside.png").write_bytes(b"outside")
    transport = _transport(tmp_path)

    with pytest.raises(McpProxyTransportError):
        transport.execute(_request(image_source))


def test_minimax_transport_rejects_unsupported_or_oversized_files(tmp_path: Path) -> None:
    (tmp_path / "material.txt").write_text("not an image", encoding="utf-8")
    (tmp_path / "large.png").write_bytes(b"12")
    transport = _transport(tmp_path, max_image_bytes=1)

    with pytest.raises(McpProxyTransportError, match="JPEG, PNG, or WebP"):
        transport.execute(_request("material.txt"))
    with pytest.raises(McpProxyTransportError, match="20 MB"):
        transport.execute(_request("large.png"))


def test_minimax_transport_rejects_other_mcp_targets(tmp_path: Path) -> None:
    transport = _transport(tmp_path)

    with pytest.raises(McpProxyTransportError, match="rejects other MCP tools"):
        transport.execute(
            McpProxyRequest(
                tool_call_id="call-1",
                target=McpToolTarget("github", "create_pull_request"),
            )
        )


def test_builder_is_disabled_by_default_and_requires_configured_key(tmp_path: Path) -> None:
    settings = load_settings(env={})
    assert build_minimax_image_mcp_transport(
        settings,
        workspace_root=tmp_path,
        env={},
    ) is None

    enabled = ZebraAgentSettings(
        profile=settings.profile,
        database_url=settings.database_url,
        api=settings.api,
        model=settings.model,
        minimax_vision=MiniMaxVisionSettings(
            enabled=True,
            api_key_env="MINIMAX_TOKEN_PLAN_KEY",
            api_host="https://api.minimaxi.com",
        ),
    )
    with pytest.raises(ValueError, match="MINIMAX_TOKEN_PLAN_KEY"):
        build_minimax_image_mcp_transport(enabled, workspace_root=tmp_path, env={})


def _transport(
    workspace_root: Path,
    *,
    max_image_bytes: int = 20 * 1024 * 1024,
) -> MiniMaxImageMcpTransport:
    return MiniMaxImageMcpTransport(
        workspace_root=workspace_root,
        api_key="secret",
        api_host="https://api.minimaxi.com",
        max_image_bytes=max_image_bytes,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"content": "ok"})
            )
        ),
    )


def _request(image_source: str) -> McpProxyRequest:
    return McpProxyRequest(
        tool_call_id="call-1",
        target=McpToolTarget("minimax", "understand_image"),
        arguments={
            "prompt": "Extract visible trades only.",
            "image_source": image_source,
        },
    )
