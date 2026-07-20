from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256

from agent_runtime.mcp_protocol import (
    McpAnyServerSpec,
    McpHttpServerSpec,
    McpProtocolError,
    McpServerSpec,
    StdioMcpSession,
)
from agent_runtime.mcp_stdio import MCP_CALL_TIMEOUT_SECONDS, MCP_DISCOVERY_TIMEOUT_SECONDS

MAX_MCP_PROMPT_PAGES = 4
MAX_MCP_PROMPTS_PER_SERVER = 64
MAX_MCP_PROMPT_ARGUMENTS = 16
MAX_MCP_PROMPT_NAME_CHARS = 128
MAX_MCP_PROMPT_DESCRIPTION_CHARS = 512
MAX_MCP_PROMPT_ARGUMENT_BYTES = 4 * 1024
MAX_MCP_PROMPT_ARGUMENT_TOTAL_BYTES = 16 * 1024
MAX_MCP_PROMPT_MESSAGES = 32
MAX_MCP_PROMPT_MESSAGE_BYTES = 16 * 1024
MAX_MCP_PROMPT_TOTAL_BYTES = 32 * 1024
_PROMPT_ID_RE = re.compile(r"^mcp-prompt:[0-9a-f]{32}$")


@dataclass(frozen=True)
class McpPromptArgument:
    name: str
    description: str
    required: bool

    def to_safe_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
        }


@dataclass(frozen=True)
class McpPrompt:
    prompt_id: str
    server_name: str
    remote_name: str
    name: str
    description: str
    arguments: tuple[McpPromptArgument, ...]

    def to_safe_mapping(self) -> dict[str, object]:
        return {
            "prompt_id": self.prompt_id,
            "name": self.name,
            "description": self.description,
            "arguments": [argument.to_safe_mapping() for argument in self.arguments],
        }


@dataclass(frozen=True)
class McpPromptMessage:
    role: str
    text: str


@dataclass(frozen=True)
class ResolvedMcpPrompt:
    prompt_id: str
    server_name: str
    name: str
    arguments: tuple[tuple[str, str], ...]
    messages: tuple[McpPromptMessage, ...]


def discover_mcp_prompts(servers: Sequence[McpAnyServerSpec]) -> tuple[McpPrompt, ...]:
    # Prompts are a stdio-only capability in Phase A; HTTP servers are skipped.
    stdio_servers = [server for server in servers if not isinstance(server, McpHttpServerSpec)]
    _require_unique_server_names(stdio_servers)
    prompts: list[McpPrompt] = []
    for server in sorted(stdio_servers, key=lambda item: item.name):
        prompts.extend(_discover_server_prompts(server))
    prompt_ids = [prompt.prompt_id for prompt in prompts]
    if len(set(prompt_ids)) != len(prompt_ids):
        raise McpProtocolError("configured MCP prompt identifiers collide")
    return tuple(sorted(prompts, key=lambda item: (item.server_name, item.name, item.prompt_id)))


def resolve_mcp_prompt(
    servers: Sequence[McpAnyServerSpec],
    prompt_id: str,
    arguments: Mapping[str, str],
) -> ResolvedMcpPrompt:
    if not isinstance(prompt_id, str) or _PROMPT_ID_RE.fullmatch(prompt_id) is None:
        raise ValueError("MCP prompt id is invalid")
    prompts = {prompt.prompt_id: prompt for prompt in discover_mcp_prompts(servers)}
    prompt = prompts.get(prompt_id)
    if prompt is None:
        raise McpProtocolError("selected MCP prompt is unavailable")
    normalized_arguments = _normalize_arguments(prompt, arguments)
    server = next(
        server
        for server in servers
        if not isinstance(server, McpHttpServerSpec) and server.name == prompt.server_name
    )
    messages = _get_prompt(server, prompt, normalized_arguments)
    return ResolvedMcpPrompt(
        prompt_id=prompt.prompt_id,
        server_name=prompt.server_name,
        name=prompt.name,
        arguments=tuple(normalized_arguments.items()),
        messages=messages,
    )


def _discover_server_prompts(server: McpServerSpec) -> list[McpPrompt]:
    prompts: list[McpPrompt] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    with StdioMcpSession(server, MCP_DISCOVERY_TIMEOUT_SECONDS) as session:
        if not session.supports("prompts"):
            return []
        _reject_server_instructions(session, server.name)
        for _ in range(MAX_MCP_PROMPT_PAGES):
            params = {"cursor": cursor} if cursor is not None else None
            result = session.request("prompts/list", params)
            entries = result.get("prompts")
            if not isinstance(entries, list):
                raise McpProtocolError(f"MCP server {server.name} returned an invalid prompt list")
            prompts.extend(_parse_prompt(server.name, entry) for entry in entries)
            if len(prompts) > MAX_MCP_PROMPTS_PER_SERVER:
                raise McpProtocolError(
                    f"MCP server {server.name} exposes more than "
                    f"{MAX_MCP_PROMPTS_PER_SERVER} prompts"
                )
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                _reject_duplicate_prompt_names(server.name, prompts)
                return prompts
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise McpProtocolError(f"MCP server {server.name} returned an invalid cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
    raise McpProtocolError(f"MCP server {server.name} exceeded the prompt-list page limit")


def _parse_prompt(server_name: str, value: object) -> McpPrompt:
    if not isinstance(value, Mapping):
        raise McpProtocolError(f"MCP server {server_name} returned an invalid prompt")
    remote_name = _bounded_identifier(
        value.get("name"), "prompt name", MAX_MCP_PROMPT_NAME_CHARS
    )
    description = _bounded_optional(
        value.get("description"), "prompt description", MAX_MCP_PROMPT_DESCRIPTION_CHARS
    )
    raw_arguments = value.get("arguments", [])
    if not isinstance(raw_arguments, list) or len(raw_arguments) > MAX_MCP_PROMPT_ARGUMENTS:
        raise McpProtocolError(f"MCP prompt {server_name}.{remote_name} has invalid arguments")
    arguments = tuple(_parse_argument(server_name, remote_name, item) for item in raw_arguments)
    names = [argument.name for argument in arguments]
    if len(set(names)) != len(names):
        raise McpProtocolError(f"MCP prompt {server_name}.{remote_name} has duplicate arguments")
    digest = sha256(f"{server_name}\0{remote_name}".encode()).hexdigest()[:32]
    return McpPrompt(
        prompt_id=f"mcp-prompt:{digest}",
        server_name=server_name,
        remote_name=remote_name,
        name=remote_name,
        description=description,
        arguments=tuple(sorted(arguments, key=lambda item: item.name)),
    )


def _parse_argument(server_name: str, prompt_name: str, value: object) -> McpPromptArgument:
    if not isinstance(value, Mapping):
        raise McpProtocolError(f"MCP prompt {server_name}.{prompt_name} has an invalid argument")
    name = _bounded_identifier(value.get("name"), "prompt argument name", 128)
    description = _bounded_optional(value.get("description"), "prompt argument description", 512)
    required = value.get("required", False)
    if not isinstance(required, bool):
        raise McpProtocolError(f"MCP prompt {server_name}.{prompt_name} has an invalid argument")
    return McpPromptArgument(name=name, description=description, required=required)


def _normalize_arguments(prompt: McpPrompt, value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("MCP prompt arguments must be a mapping")
    declared = {argument.name: argument for argument in prompt.arguments}
    if len(value) > len(declared):
        raise ValueError("MCP prompt arguments contain unknown fields")
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ValueError("MCP prompt arguments must contain string keys and values")
    unknown = sorted(set(value) - set(declared))
    if unknown:
        raise ValueError(f"MCP prompt arguments are unknown: {', '.join(unknown)}")
    missing = sorted(
        argument.name
        for argument in prompt.arguments
        if argument.required and argument.name not in value
    )
    if missing:
        raise ValueError(f"MCP prompt arguments are missing: {', '.join(missing)}")
    total = 0
    normalized: dict[str, str] = {}
    for name in sorted(value):
        item = value[name]
        size = len(item.encode("utf-8"))
        if size > MAX_MCP_PROMPT_ARGUMENT_BYTES:
            raise ValueError(f"MCP prompt argument {name} exceeds the configured limit")
        total += size
        if total > MAX_MCP_PROMPT_ARGUMENT_TOTAL_BYTES:
            raise ValueError("MCP prompt arguments exceed the configured total limit")
        normalized[name] = item
    return normalized


def _get_prompt(
    server: McpServerSpec,
    prompt: McpPrompt,
    arguments: Mapping[str, str],
) -> tuple[McpPromptMessage, ...]:
    with StdioMcpSession(server, MCP_CALL_TIMEOUT_SECONDS) as session:
        if not session.supports("prompts"):
            raise McpProtocolError(f"MCP server {server.name} no longer declares prompts")
        _reject_server_instructions(session, server.name)
        result = session.request(
            "prompts/get", {"name": prompt.remote_name, "arguments": dict(arguments)}
        )
    if result.get("instructions") is not None:
        raise McpProtocolError("MCP prompt returned unsupported server instructions")
    raw_messages = result.get("messages")
    if (
        not isinstance(raw_messages, list)
        or not raw_messages
        or len(raw_messages) > MAX_MCP_PROMPT_MESSAGES
    ):
        raise McpProtocolError("MCP prompt returned an invalid message list")
    messages: list[McpPromptMessage] = []
    total = 0
    for raw_message in raw_messages:
        message = _parse_message(raw_message)
        total += len(message.text.encode("utf-8"))
        if total > MAX_MCP_PROMPT_TOTAL_BYTES:
            raise McpProtocolError("MCP prompt output exceeds the configured total limit")
        messages.append(message)
    return tuple(messages)


def _parse_message(value: object) -> McpPromptMessage:
    if not isinstance(value, Mapping) or set(value) != {"role", "content"}:
        raise McpProtocolError("MCP prompt returned a malformed message")
    role = value.get("role")
    if role not in {"user", "assistant"}:
        raise McpProtocolError("MCP prompt returned an unsupported role")
    content = value.get("content")
    if not isinstance(content, Mapping) or set(content) != {"type", "text"}:
        raise McpProtocolError("MCP prompt returned unsupported content")
    if content.get("type") != "text" or not isinstance(content.get("text"), str):
        raise McpProtocolError("MCP prompt returned unsupported content")
    text = content["text"]
    assert isinstance(text, str)
    size = len(text.encode("utf-8"))
    if not text.strip() or size > MAX_MCP_PROMPT_MESSAGE_BYTES:
        raise McpProtocolError("MCP prompt returned invalid or oversized text")
    return McpPromptMessage(role=role, text=text)


def _reject_server_instructions(session: StdioMcpSession, server_name: str) -> None:
    if session.has_server_instructions:
        raise McpProtocolError(f"MCP server {server_name} returned unsupported instructions")


def _reject_duplicate_prompt_names(server_name: str, prompts: Sequence[McpPrompt]) -> None:
    names = [prompt.remote_name for prompt in prompts]
    if len(set(names)) != len(names):
        raise McpProtocolError(f"MCP server {server_name} returned duplicate prompt names")


def _require_unique_server_names(servers: Sequence[McpServerSpec]) -> None:
    names = [server.name for server in servers]
    if len(set(names)) != len(names):
        raise McpProtocolError("MCP server names must be unique")


def _bounded_required(value: object, label: str, maximum: int) -> str:
    normalized = _bounded_optional(value, label, maximum)
    if not normalized:
        raise McpProtocolError(f"{label} must not be blank")
    return normalized


def _bounded_identifier(value: object, label: str, maximum: int) -> str:
    normalized = _bounded_required(value, label, maximum)
    assert isinstance(value, str)
    if value != normalized:
        raise McpProtocolError(f"{label} contains surrounding whitespace")
    return normalized


def _bounded_optional(value: object, label: str, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise McpProtocolError(f"{label} must be a string")
    normalized = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise McpProtocolError(f"{label} contains control characters")
    if len(normalized) > maximum:
        raise McpProtocolError(f"{label} exceeds {maximum} characters")
    return normalized
