from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime.workspace import LocalWorkspace
from agent_tools import ToolExecutor, ToolRegistry, WorkspaceSearchTool
from agent_tools.errors import ToolArgumentError


def _call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.search",
        arguments=arguments,
        created_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
    )


def _executor(root: Path) -> ToolExecutor:
    registry = ToolRegistry()
    tool = WorkspaceSearchTool(LocalWorkspace(root))
    registry.register(tool.contract, tool.handle)
    return ToolExecutor(registry)


def test_content_search_returns_ordered_bounded_evidence(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("skip\nneedle second\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("needle first\n", encoding="utf-8")

    result = _executor(tmp_path).execute(_call({"query": "needle"}))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output.splitlines() == [
        "a.txt:1:1:needle first",
        "b.txt:2:1:needle second",
    ]
    assert result.metadata["match_count"] == 2
    assert result.metadata["returned_count"] == 2
    assert result.metadata["truncated"] is False
    assert result.metadata["next_offset"] is None


def test_search_advertises_optional_non_blank_root(tmp_path: Path) -> None:
    registry = ToolRegistry()
    tool = WorkspaceSearchTool(LocalWorkspace(tmp_path))
    registry.register(tool.contract, tool.handle)

    definition = registry.model_tools()[0]

    assert definition.parameters["required"] == ["query"]
    assert definition.parameters["properties"]["path"]["minLength"] == 1


def test_filename_search_supports_root_glob_and_pagination(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    for name in ("alpha.py", "alpha.txt", "beta_alpha.py"):
        (source / name).write_text("content", encoding="utf-8")

    result = _executor(tmp_path).execute(
        _call(
            {
                "query": "alpha",
                "mode": "files",
                "path": "src",
                "glob": "*.py",
                "limit": 1,
                "offset": 1,
            }
        )
    )

    assert result.output == "src/beta_alpha.py"
    assert result.metadata["path"] == "src"
    assert result.metadata["match_count"] == 2
    assert result.metadata["next_offset"] is None


def test_search_excludes_hidden_binary_large_and_symlink_files(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-search-secret.txt"
    outside.write_text("needle", encoding="utf-8")
    (tmp_path / ".env").write_text("needle", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"needle\x00binary")
    (tmp_path / "large.txt").write_bytes(b"needle" + b"x" * 1_048_576)
    (tmp_path / "linked.txt").symlink_to(outside)

    result = _executor(tmp_path).execute(_call({"query": "needle"}))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == ""

    hidden_root = _executor(tmp_path).execute(
        _call({"query": "needle", "path": "." + "hidden"})
    )
    assert hidden_root.status is ToolCallStatus.FAILED
    assert hidden_root.metadata["reason"] == "hidden_path"


def test_search_rejects_workspace_escape_and_symlink_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-search-root"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "outside"
    link.symlink_to(outside, target_is_directory=True)
    executor = _executor(tmp_path)

    escaped = executor.execute(_call({"query": "x", "path": "../"}))
    linked = executor.execute(_call({"query": "x", "path": "outside"}))

    assert escaped.status is ToolCallStatus.FAILED
    assert escaped.metadata["reason"] == "path_outside_workspace"
    assert linked.status is ToolCallStatus.FAILED
    assert linked.metadata["reason"] == "path_outside_workspace"


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"query": ""}, "query.*non-blank"),
        ({"query": "x", "mode": "regex"}, "mode"),
        ({"query": "x", "glob": 3}, "glob.*string"),
        ({"query": "x", "limit": 0}, "limit.*integer"),
        ({"query": "x", "offset": True}, "offset.*integer"),
    ],
)
def test_search_rejects_malformed_arguments(
    tmp_path: Path, arguments: dict[str, object], message: str
) -> None:
    with pytest.raises(ToolArgumentError, match=message):
        _executor(tmp_path).execute(_call(arguments))


def test_search_reports_deterministic_next_offset(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"item-{index}.txt").write_text("proof", encoding="utf-8")

    result = _executor(tmp_path).execute(_call({"query": "proof", "limit": 2}))

    assert result.metadata["returned_count"] == 2
    assert result.metadata["truncated"] is True
    assert result.metadata["next_offset"] == 2
    assert result.metadata["hint"] is not None


def test_search_enforces_line_and_output_byte_ceilings(tmp_path: Path) -> None:
    long_line = "proof" + "x" * 1_000
    for index in range(100):
        (tmp_path / f"item-{index:03}.txt").write_text(long_line, encoding="utf-8")

    result = _executor(tmp_path).execute(
        _call({"query": "proof", "limit": 100})
    )

    assert len(result.output.encode("utf-8")) <= 32_768
    assert all(len(line.rsplit(":", 1)[-1]) == 500 for line in result.output.splitlines())
    assert result.metadata["returned_count"] < 100
    assert result.metadata["truncated"] is True
    assert result.metadata["next_offset"] == result.metadata["returned_count"]
