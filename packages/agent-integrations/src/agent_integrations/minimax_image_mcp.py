from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

import httpx
from agent_tools.errors import McpProxyTransportError
from agent_tools.mcp_proxy import McpProxyRequest, McpProxyResponse
from zebra_agent_config import ZebraAgentSettings

_ALLOWED_HOSTS = frozenset({"api.minimax.io", "api.minimaxi.com"})
_MEDIA_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


class MiniMaxImageMcpTransport:
    """Workspace-bounded adapter for MiniMax's official understand_image tool."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        api_key: str,
        api_host: str,
        timeout_s: float = 60.0,
        max_image_bytes: int = _MAX_IMAGE_BYTES,
        client: httpx.Client | None = None,
    ) -> None:
        self._workspace_root = workspace_root.expanduser().resolve(strict=True)
        self._api_key = api_key.strip()
        self._api_host = _validated_api_host(api_host)
        if not self._api_key:
            raise ValueError("MiniMax API key must not be blank")
        if max_image_bytes <= 0:
            raise ValueError("max_image_bytes must be positive")
        self._timeout_s = timeout_s
        self._max_image_bytes = max_image_bytes
        self._client = client

    def execute(self, request: McpProxyRequest) -> McpProxyResponse:
        if (request.target.server_name, request.target.tool_name) != (
            "minimax",
            "understand_image",
        ):
            raise McpProxyTransportError("MiniMax vision transport rejects other MCP tools")
        prompt = _required_string(request.arguments.get("prompt"), "prompt")
        if len(prompt) > 8_000:
            raise McpProxyTransportError("MiniMax image prompt exceeds 8000 characters")
        image_source = _required_string(
            request.arguments.get("image_source"),
            "image_source",
        )
        image_path, media_type = self._validated_image(image_source)
        image_bytes = image_path.read_bytes()
        response_data = self._post(
            {
                "prompt": prompt,
                "image_url": (
                    f"data:{media_type};base64,"
                    f"{base64.b64encode(image_bytes).decode('ascii')}"
                ),
            }
        )
        content = response_data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise McpProxyTransportError("MiniMax image response did not contain text")
        return McpProxyResponse(
            output=content.strip(),
            metadata={
                "provider": "minimax",
                "billable_tool_calls": 1,
                "source_file": image_path.name,
                "source_sha256": hashlib.sha256(image_bytes).hexdigest(),
            },
        )

    def _validated_image(self, image_source: str) -> tuple[Path, str]:
        if image_source.startswith(("http://", "https://", "data:")):
            raise McpProxyTransportError("image_source must be a local workspace file")
        raw_path = Path(image_source)
        candidate = raw_path if raw_path.is_absolute() else self._workspace_root / raw_path
        try:
            resolved = candidate.expanduser().resolve(strict=True)
            resolved.relative_to(self._workspace_root)
        except (FileNotFoundError, ValueError) as exc:
            raise McpProxyTransportError(
                "image_source must resolve inside the current workspace"
            ) from exc
        if not resolved.is_file():
            raise McpProxyTransportError("image_source must be a regular file")
        media_type = _MEDIA_TYPES.get(resolved.suffix.lower())
        if media_type is None:
            raise McpProxyTransportError("image_source must be JPEG, PNG, or WebP")
        if resolved.stat().st_size > self._max_image_bytes:
            raise McpProxyTransportError("image_source exceeds the 20 MB limit")
        return resolved, media_type

    def _post(self, body: dict[str, str]) -> dict[str, object]:
        client = self._client or httpx.Client(timeout=self._timeout_s)
        should_close = self._client is None
        try:
            response = client.post(
                f"{self._api_host}/v1/coding_plan/vlm",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise McpProxyTransportError(
                f"MiniMax image request failed: {type(exc).__name__}"
            ) from exc
        finally:
            if should_close:
                client.close()
        if not isinstance(payload, dict):
            raise McpProxyTransportError("MiniMax image response must be a JSON object")
        return payload


def build_minimax_image_mcp_transport(
    settings: ZebraAgentSettings,
    *,
    workspace_root: Path,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> MiniMaxImageMcpTransport | None:
    config = settings.minimax_vision
    if not config.enabled:
        return None
    values = os.environ if env is None else env
    api_key = values.get(config.api_key_env, "").strip()
    if not api_key:
        raise ValueError(f"missing API key in environment variable {config.api_key_env}")
    return MiniMaxImageMcpTransport(
        workspace_root=workspace_root,
        api_key=api_key,
        api_host=config.api_host,
        client=client,
    )


def _validated_api_host(value: str) -> str:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_HOSTS
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MiniMax API host must be the official global or mainland host")
    return f"https://{parsed.hostname}"


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpProxyTransportError(f"{field_name} must be a non-empty string")
    return value.strip()
