from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelToolDefinition,
    ModelUsage,
)
from agent_core.domain.tools import ToolCall
from zebra_agent_config import ZebraAgentSettings

CHAT_COMPLETIONS_PATH = "/chat/completions"


class OpenAICompatibleModelGateway:
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_s = timeout_s
        self._client = client

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
    ) -> ModelCompletion:
        tool_names = _provider_tool_names(tools)
        request_body = {
            "model": self._model_name,
            "messages": [_serialize_message(message) for message in messages],
            "stream": False,
        }
        if tools:
            request_body["tools"] = [
                _serialize_tool(tool, provider_name=provider_name)
                for tool, provider_name in zip(tools, tool_names, strict=True)
            ]
        started = perf_counter()
        response_data = self._post_chat_completion(request_body)
        latency_ms = int((perf_counter() - started) * 1000)
        return _parse_completion(
            response_data,
            provider_name=self._provider_name,
            default_model_name=self._model_name,
            latency_ms=latency_ms,
            internal_tool_names={
                provider_name: tool.name
                for tool, provider_name in zip(tools, tool_names, strict=True)
            },
        )

    def _post_chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.Client(timeout=self._timeout_s)
        should_close = self._client is None
        try:
            response = client.post(
                f"{self._base_url}{CHAT_COMPLETIONS_PATH}",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("model gateway response must be a JSON object")
            return payload
        finally:
            if should_close:
                client.close()


def build_model_gateway(
    settings: ZebraAgentSettings,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> OpenAICompatibleModelGateway:
    values = dict(env or {})
    if env is None:
        values.update(_read_defaults(Path(".env")))
        values.update(_read_defaults(Path(".env.local")))
    api_key = values.get(settings.model.api_key_env)
    if api_key is None:
        import os

        api_key = os.environ.get(settings.model.api_key_env)
    normalized_key = (api_key or "").strip()
    if not normalized_key:
        raise ValueError(
            f"missing API key in environment variable {settings.model.api_key_env}"
        )
    return OpenAICompatibleModelGateway(
        provider_name=settings.model.provider,
        base_url=settings.model.base_url,
        api_key=normalized_key,
        model_name=settings.model.model,
        client=client,
    )


def _read_defaults(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    defaults: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        defaults[key.strip()] = value.strip()
    return defaults


def _serialize_message(message: SessionMessage) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": message.role.value,
        "content": message.content,
    }
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tool_call.provider_call_id or str(tool_call.tool_call_id),
                "type": "function",
                "function": {
                    "name": _provider_tool_name(
                        tool_call.provider_tool_name or tool_call.name
                    ),
                    "arguments": _serialize_tool_arguments(
                        tool_call.provider_arguments
                        if tool_call.provider_arguments is not None
                        else tool_call.arguments
                    ),
                },
            }
            for tool_call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    return payload


def _serialize_tool_arguments(arguments: Mapping[str, object]) -> str:
    import json

    return json.dumps(arguments, separators=(",", ":"), sort_keys=True)


def _provider_tool_name(name: str) -> str:
    return name.replace(".", "__")


def _provider_tool_names(tools: tuple[ModelToolDefinition, ...]) -> tuple[str, ...]:
    names = tuple(_provider_tool_name(tool.name) for tool in tools)
    if len(set(names)) != len(names):
        raise ValueError("model tool names collide after provider normalization")
    for name in names:
        if not name or len(name) > 64 or any(
            not (character.isascii() and (character.isalnum() or character in "_-"))
            for character in name
        ):
            raise ValueError(f"model tool name is not provider compatible: {name}")
    return names


def _serialize_tool(
    tool: ModelToolDefinition,
    *,
    provider_name: str,
) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": provider_name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _parse_completion(
    payload: dict[str, Any],
    *,
    provider_name: str,
    default_model_name: str,
    latency_ms: int,
    internal_tool_names: Mapping[str, str] | None = None,
) -> ModelCompletion:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("model gateway response must include at least one choice")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("model gateway choice must be an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("model gateway choice must include a message object")
    tool_calls = _parse_tool_calls(
        message.get("tool_calls"),
        internal_tool_names=internal_tool_names or {},
    )
    content = _assistant_content(message.get("content"), has_tool_calls=bool(tool_calls))
    created_at = datetime.now(UTC)
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=created_at,
            tool_calls=tuple(tool_calls),
        ),
        tool_calls=tuple(tool_calls),
        call_metadata=ModelCallMetadata(
            provider=provider_name,
            model_name=_optional_str(payload.get("model")) or default_model_name,
            latency_ms=latency_ms,
            usage=_parse_usage(payload.get("usage")),
        ),
    )


def _assistant_content(value: object, *, has_tool_calls: bool) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if has_tool_calls:
        return "Tool calls proposed."
    raise ValueError("model gateway assistant message content must not be blank")


def _parse_tool_calls(
    value: object,
    *,
    internal_tool_names: Mapping[str, str],
) -> list[ToolCall]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("tool_calls must be a list when present")
    created_at = datetime.now(UTC)
    parsed: list[ToolCall] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("tool_call entry must be an object")
        function = item.get("function")
        if not isinstance(function, dict):
            raise ValueError("tool_call must include a function object")
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool_call function name must not be blank")
        provider_call_id = item.get("id")
        if not isinstance(provider_call_id, str) or not provider_call_id.strip():
            raise ValueError("tool_call id must not be blank")
        if internal_tool_names:
            try:
                name = internal_tool_names[name]
            except KeyError as exc:
                raise ValueError(f"model returned an unadvertised tool call: {name}") from exc
        arguments = _parse_tool_arguments(function.get("arguments"))
        parsed.append(
            ToolCall(
                tool_call_id=new_tool_call_id(),
                name=name,
                arguments=arguments,
                created_at=created_at,
                provider_call_id=provider_call_id,
            )
        )
    return parsed


def _parse_tool_arguments(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        import json

        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("tool_call arguments JSON must decode to an object")
        return parsed
    raise ValueError("tool_call arguments must be an object or JSON string")


def _parse_usage(value: object) -> ModelUsage:
    if not isinstance(value, dict):
        return ModelUsage()
    return ModelUsage(
        input_tokens=_optional_int(value.get("prompt_tokens")),
        output_tokens=_optional_int(value.get("completion_tokens")),
        total_tokens=_optional_int(value.get("total_tokens")),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError("usage token fields must be integers")
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("string fields must be strings when present")
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
