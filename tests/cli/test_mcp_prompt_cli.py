import sys
from pathlib import Path

import pytest
from agent_runtime import McpPrompt, McpPromptArgument, McpPromptMessage, ResolvedMcpPrompt
from zebra_agent_cli.cli import execute
from zebra_agent_config import ApiSettings, McpServerSettings, ModelSettings, ZebraAgentSettings

PROMPT_ID = "mcp-prompt:" + "2" * 32


def test_cli_lists_safe_prompt_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "zebra_agent_cli.mcp_prompt_commands.discover_mcp_prompts",
        lambda _servers: (
            McpPrompt(
                prompt_id=PROMPT_ID,
                server_name="hidden",
                remote_name="summarize",
                name="summarize",
                description="Summarize material.",
                arguments=(McpPromptArgument("material", "", True),),
            ),
        ),
    )

    result = execute(["mcp-prompts"], settings=_settings(Path(":memory:")))

    assert result.payload["prompt_count"] == 1
    assert result.payload["prompts"][0]["prompt_id"] == PROMPT_ID
    assert result.payload["prompts"][0]["available"] is True
    assert "hidden" not in repr(result.payload)


def test_cli_queued_run_persists_one_prompt_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "sessions.sqlite"
    monkeypatch.setattr(
        "zebra_agent_cli.run_command_execution.resolve_mcp_prompt",
        lambda _servers, prompt_id, arguments: ResolvedMcpPrompt(
            prompt_id=prompt_id,
            server_name="fixture",
            name="summarize",
            arguments=tuple(sorted(arguments.items())),
            messages=(McpPromptMessage("user", "Summarize captured material."),),
        ),
    )

    result = execute(
        [
            "run",
            "Use template",
            "--network-profile",
            "mcp-proxy-only",
            "--mcp-prompt",
            PROMPT_ID,
            "--mcp-prompt-arg",
            "material=bounded",
        ],
        settings=_settings(database),
    )

    assert result.payload["mcp_prompt_id"] == PROMPT_ID
    assert result.payload["attachments"][0]["source_type"] == "mcp_prompt"
    assert result.payload["attachments"][0]["source_argument_names"] == ["material"]
    assert "Summarize captured material" not in repr(result.payload)


@pytest.mark.parametrize(
    "arguments, reason",
    [
        (["--mcp-prompt", PROMPT_ID, "--mcp-prompt", PROMPT_ID], "at most one"),
        (["--mcp-prompt-arg", "topic=value"], "requires --mcp-prompt"),
        (
            [
                "--mcp-prompt",
                PROMPT_ID,
                "--mcp-prompt-arg",
                "topic=one",
                "--mcp-prompt-arg",
                "topic=two",
            ],
            "duplicate MCP prompt argument",
        ),
    ],
)
def test_cli_rejects_ambiguous_prompt_selection(
    tmp_path: Path,
    arguments: list[str],
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        execute(["run", "invalid", *arguments], settings=_settings(tmp_path / "sessions.sqlite"))


def _settings(database: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        mcp_servers=(McpServerSettings(name="fixture", command=sys.executable),),
    )
