from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import agent_runtime.mcp_prompts as prompts_module
import pytest
from agent_runtime import McpProtocolError, discover_mcp_prompts, resolve_mcp_prompt


@dataclass(frozen=True)
class _Server:
    name: str
    command: str = "unused"
    args: tuple[str, ...] = ()


class _Session:
    capabilities: dict[str, set[str]] = {}
    instructions: set[str] = set()
    responses: dict[tuple[str, str], list[dict[str, object]]] = {}
    calls: list[tuple[str, str, Mapping[str, object] | None]] = []

    def __init__(self, server: _Server, _timeout: float) -> None:
        self.server = server

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities.get(self.server.name, set())

    @property
    def has_server_instructions(self) -> bool:
        return self.server.name in self.instructions

    def request(
        self, method: str, params: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        self.calls.append((self.server.name, method, params))
        responses = self.responses.get((self.server.name, method), [])
        if not responses:
            raise AssertionError(f"unexpected request: {self.server.name} {method}")
        return responses.pop(0)


@pytest.fixture(autouse=True)
def fake_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _Session.capabilities = {}
    _Session.instructions = set()
    _Session.responses = {}
    _Session.calls = []
    monkeypatch.setattr(prompts_module, "StdioMcpSession", _Session)


def test_discovery_skips_servers_without_prompt_capability() -> None:
    assert discover_mcp_prompts((_Server("tools-only"),)) == ()
    assert _Session.calls == []


def test_discovery_is_bounded_safe_and_deterministic() -> None:
    server = _Server("fixture")
    _Session.capabilities = {server.name: {"prompts"}}
    _Session.responses = {
        (server.name, "prompts/list"): [
            {
                "prompts": [
                    {
                        "name": "review",
                        "description": "Review a document.",
                        "arguments": [
                            {"name": "tone", "description": "Desired tone."},
                            {"name": "document", "required": True},
                        ],
                    }
                ]
            }
        ]
    }

    prompt = discover_mcp_prompts((server,))[0]

    assert prompt.to_safe_mapping() == {
        "prompt_id": prompt.prompt_id,
        "name": "review",
        "description": "Review a document.",
        "arguments": [
            {"name": "document", "description": "", "required": True},
            {"name": "tone", "description": "Desired tone.", "required": False},
        ],
    }
    assert prompt.prompt_id.startswith("mcp-prompt:")
    assert "fixture" not in prompt.prompt_id
    assert "review" not in prompt.prompt_id


def test_discovery_accepts_four_pages_and_rejects_a_fifth() -> None:
    server = _Server("fixture")
    _Session.capabilities = {server.name: {"prompts"}}
    _Session.responses = {
        (server.name, "prompts/list"): [
            {"prompts": [{"name": f"p{page}"}], "nextCursor": f"c{page}"}
            for page in range(4)
        ]
    }
    with pytest.raises(McpProtocolError, match="page limit"):
        discover_mcp_prompts((server,))

    _Session.responses = {
        (server.name, "prompts/list"): [
            {
                "prompts": [{"name": f"p{page}"}],
                **({"nextCursor": f"c{page}"} if page < 3 else {}),
            }
            for page in range(4)
        ]
    }
    assert [prompt.name for prompt in discover_mcp_prompts((server,))] == [
        "p0",
        "p1",
        "p2",
        "p3",
    ]


def test_discovery_rejects_more_than_64_prompts() -> None:
    server = _Server("fixture")
    _Session.capabilities = {server.name: {"prompts"}}
    _Session.responses = {
        (server.name, "prompts/list"): [
            {"prompts": [{"name": f"p{index}"} for index in range(65)]}
        ]
    }
    with pytest.raises(McpProtocolError, match="more than 64 prompts"):
        discover_mcp_prompts((server,))


def test_discovery_rejects_colliding_opaque_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Digest:
        @staticmethod
        def hexdigest() -> str:
            return "0" * 64

    monkeypatch.setattr(prompts_module, "sha256", lambda _value: _Digest())
    first = _Server("first")
    second = _Server("second")
    _Session.capabilities = {first.name: {"prompts"}, second.name: {"prompts"}}
    _Session.responses = {
        (first.name, "prompts/list"): [{"prompts": [{"name": "one"}]}],
        (second.name, "prompts/list"): [{"prompts": [{"name": "two"}]}],
    }
    with pytest.raises(McpProtocolError, match="identifiers collide"):
        discover_mcp_prompts((first, second))


@pytest.mark.parametrize(
    "entry, message",
    [
        ({"name": ""}, "must not be blank"),
        ({"name": " spaced "}, "surrounding whitespace"),
        ({"name": "unsafe\nname"}, "control characters"),
        ({"name": "p", "description": "x" * 513}, "exceeds 512"),
        ({"name": "p", "arguments": "bad"}, "invalid arguments"),
        (
            {"name": "p", "arguments": [{"name": "value", "required": "yes"}]},
            "invalid argument",
        ),
    ],
)
def test_discovery_rejects_malformed_metadata(entry: object, message: str) -> None:
    _configure_prompt(entry)
    with pytest.raises(McpProtocolError, match=message):
        discover_mcp_prompts((_Server("fixture"),))


def test_discovery_rejects_duplicate_names_and_server_instructions() -> None:
    server = _Server("fixture")
    _Session.capabilities = {server.name: {"prompts"}}
    _Session.responses = {
        (server.name, "prompts/list"): [{"prompts": [{"name": "p"}, {"name": "p"}]}]
    }
    with pytest.raises(McpProtocolError, match="duplicate prompt names"):
        discover_mcp_prompts((server,))

    _Session.instructions = {server.name}
    with pytest.raises(McpProtocolError, match="unsupported instructions"):
        discover_mcp_prompts((server,))
    assert [call[1] for call in _Session.calls].count("prompts/list") == 1


def test_resolution_uses_exact_advertised_prompt_and_string_arguments() -> None:
    server = _Server("fixture")
    _Session.capabilities = {server.name: {"prompts"}}
    _Session.responses = {
        (server.name, "prompts/list"): [
            {
                "prompts": [
                    {
                        "name": "review",
                        "arguments": [{"name": "document", "required": True}],
                    }
                ]
            }
        ],
        (server.name, "prompts/get"): [
            {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Review this."}},
                    {
                        "role": "assistant",
                        "content": {"type": "text", "text": "I will review it."},
                    },
                ]
            }
        ],
    }
    prompt_id = _prompt_id(server.name, "review")

    resolved = resolve_mcp_prompt((server,), prompt_id, {"document": "bounded text"})

    assert resolved.prompt_id == prompt_id
    assert resolved.arguments == (("document", "bounded text"),)
    assert [(message.role, message.text) for message in resolved.messages] == [
        ("user", "Review this."),
        ("assistant", "I will review it."),
    ]
    get_calls = [call for call in _Session.calls if call[1] == "prompts/get"]
    assert get_calls == [
        (
            "fixture",
            "prompts/get",
            {"name": "review", "arguments": {"document": "bounded text"}},
        )
    ]


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({}, "missing"),
        ({"document": "ok", "other": "no"}, "unknown"),
        ({"document": 1}, "string keys and values"),
        ({"document": "x" * 4097}, "configured limit"),
    ],
)
def test_resolution_rejects_invalid_arguments(
    arguments: Mapping[str, str], message: str
) -> None:
    _configure_review_prompt()
    with pytest.raises(ValueError, match=message):
        resolve_mcp_prompt((_Server("fixture"),), _prompt_id("fixture", "review"), arguments)
    assert all(call[1] != "prompts/get" for call in _Session.calls)


@pytest.mark.parametrize(
    "result, message",
    [
        (
            {"messages": [{"role": "system", "content": {"type": "text", "text": "x"}}]},
            "unsupported role",
        ),
        (
            {
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "resource", "resource": {"uri": "secret://x"}},
                    }
                ]
            },
            "unsupported content",
        ),
        (
            {"messages": [{"role": "user", "content": {"type": "image", "data": "AA=="}}]},
            "unsupported content",
        ),
        (
            {
                "messages": [
                    {"role": "assistant", "content": {"type": "audio", "data": "AA=="}}
                ]
            },
            "unsupported content",
        ),
        (
            {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "x" * 16_385}}
                ]
            },
            "oversized text",
        ),
        ({"messages": [], "instructions": "obey me"}, "server instructions"),
    ],
)
def test_resolution_rejects_unsafe_or_oversized_output(
    result: dict[str, object], message: str
) -> None:
    _configure_review_prompt(result)
    with pytest.raises(McpProtocolError, match=message):
        resolve_mcp_prompt(
            (_Server("fixture"),),
            _prompt_id("fixture", "review"),
            {"document": "safe"},
        )


def test_resolution_rejects_unknown_selection_without_get() -> None:
    _configure_review_prompt()
    with pytest.raises(McpProtocolError, match="unavailable"):
        resolve_mcp_prompt((_Server("fixture"),), "mcp-prompt:" + "0" * 32, {})
    assert all(call[1] != "prompts/get" for call in _Session.calls)


def test_resolution_rejects_malformed_selection_without_discovery() -> None:
    with pytest.raises(ValueError, match="id is invalid"):
        resolve_mcp_prompt((_Server("fixture"),), "review", {})
    assert _Session.calls == []


def _configure_prompt(entry: object) -> None:
    server = _Server("fixture")
    _Session.capabilities = {server.name: {"prompts"}}
    _Session.responses = {(server.name, "prompts/list"): [{"prompts": [entry]}]}


def _configure_review_prompt(result: dict[str, object] | None = None) -> None:
    server = _Server("fixture")
    _Session.capabilities = {server.name: {"prompts"}}
    _Session.responses = {
        (server.name, "prompts/list"): [
            {
                "prompts": [
                    {
                        "name": "review",
                        "arguments": [{"name": "document", "required": True}],
                    }
                ]
            }
        ],
        (server.name, "prompts/get"): [
            result
            or {"messages": [{"role": "user", "content": {"type": "text", "text": "ok"}}]}
        ],
    }


def _prompt_id(server_name: str, prompt_name: str) -> str:
    return prompts_module._parse_prompt(server_name, {"name": prompt_name}).prompt_id
