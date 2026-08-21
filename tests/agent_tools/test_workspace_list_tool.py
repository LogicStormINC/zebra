import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime.workspace import LocalWorkspace
from agent_tools import ToolExecutor, ToolRegistry, WorkspaceListTool
from agent_tools.builtin import listing
from agent_tools.errors import ToolArgumentError


def _call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.list",
        arguments=arguments,
        created_at=datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
    )


def _executor(root: Path) -> ToolExecutor:
    registry = ToolRegistry()
    tool = WorkspaceListTool(LocalWorkspace(root))
    registry.register(tool.contract, tool.handle)
    return ToolExecutor(registry)


def test_list_returns_stable_directories_before_files(tmp_path: Path) -> None:
    (tmp_path / "z-dir").mkdir()
    (tmp_path / "a-dir").mkdir()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "z.txt").write_text("zebra", encoding="utf-8")

    result = _executor(tmp_path).execute(_call({}))

    assert result.status is ToolCallStatus.EXECUTED
    assert json.loads(result.output) == {
        "path": ".",
        "entries": [
            {"path": "a-dir", "kind": "directory", "size": None},
            {"path": "z-dir", "kind": "directory", "size": None},
            {"path": "a.txt", "kind": "file", "size": 1},
            {"path": "z.txt", "kind": "file", "size": 5},
        ],
    }
    assert result.metadata["returned_count"] == 4
    assert result.metadata["truncated"] is False


def test_list_advertises_optional_non_blank_root(tmp_path: Path) -> None:
    registry = ToolRegistry()
    tool = WorkspaceListTool(LocalWorkspace(tmp_path))
    registry.register(tool.contract, tool.handle)

    definition = registry.model_tools()[0]

    assert definition.parameters["required"] == []
    assert definition.parameters["properties"]["path"]["minLength"] == 1


def test_list_supports_relative_root_depth_and_pagination(tmp_path: Path) -> None:
    materials = tmp_path / "materials"
    nested = materials / "nested"
    nested.mkdir(parents=True)
    (materials / "brief.txt").write_text("brief", encoding="utf-8")
    (nested / "proof.txt").write_text("proof", encoding="utf-8")

    result = _executor(tmp_path).execute(
        _call({"path": "materials", "depth": 2, "limit": 2})
    )

    assert [entry["path"] for entry in json.loads(result.output)["entries"]] == [
        "materials/nested",
        "materials/brief.txt",
    ]
    assert result.metadata["matched_entries"] == 3
    assert result.metadata["next_offset"] == 2
    assert result.metadata["truncated"] is True


def test_list_excludes_hidden_generated_and_symlink_entries(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-list-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    for name in (".git", "node_modules", "venv", "build"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "secret.txt").write_text("secret", encoding="utf-8")
    (tmp_path / ".env").write_text("secret", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)
    (tmp_path / "build-file").write_text("visible", encoding="utf-8")

    result = _executor(tmp_path).execute(_call({"depth": 4}))

    assert [entry["path"] for entry in json.loads(result.output)["entries"]] == [
        "build-file"
    ]


@pytest.mark.parametrize(
    "path, reason",
    [
        ("../outside", "path_outside_workspace"),
        ("/tmp", "path_outside_workspace"),
        (".hidden", "hidden_path"),
        ("missing", "path_not_found"),
        ("file.txt", "not_a_directory"),
        ("linked", "symlink_path"),
    ],
)
def test_list_rejects_unsafe_or_invalid_roots(
    tmp_path: Path, path: str, reason: str
) -> None:
    (tmp_path / "file.txt").write_text("file", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "linked").symlink_to(target, target_is_directory=True)

    result = _executor(tmp_path).execute(_call({"path": path}))

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == reason


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"path": 7}, "path.*string"),
        ({"path": " "}, "path.*non-blank"),
        ({"depth": 0}, "depth.*integer"),
        ({"depth": True}, "depth.*integer"),
        ({"limit": 201}, "limit.*integer"),
        ({"offset": -1}, "offset.*integer"),
        ({"extra": True}, "unsupported arguments"),
    ],
)
def test_list_rejects_malformed_arguments(
    tmp_path: Path, arguments: dict[str, object], message: str
) -> None:
    with pytest.raises(ToolArgumentError, match=message):
        _executor(tmp_path).execute(_call(arguments))


def test_list_enforces_scan_and_output_ceilings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(5):
        (tmp_path / f"item-{index}.txt").write_text("proof", encoding="utf-8")
    monkeypatch.setattr(listing, "MAX_SCANNED_ENTRIES", 3)

    scan_result = _executor(tmp_path).execute(_call({}))

    assert scan_result.metadata["scanned_entries"] == 3
    assert scan_result.metadata["scan_truncated"] is True
    monkeypatch.setattr(listing, "MAX_SCANNED_ENTRIES", 10_000)
    monkeypatch.setattr(listing, "MAX_OUTPUT_BYTES", 90)

    output_result = _executor(tmp_path).execute(_call({"path": ".", "limit": 5}))

    assert len(output_result.output.encode("utf-8")) <= 90
    assert output_result.metadata["output_truncated"] is True
    assert output_result.metadata["next_offset"] == output_result.metadata["returned_count"]
