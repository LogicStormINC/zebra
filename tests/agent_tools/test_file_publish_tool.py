from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime.workspace import LocalWorkspace
from agent_tools.builtin.publish import FilePublishTool


def _call(**arguments: object) -> ToolCall:
    return ToolCall(
        tool_call_id=uuid4(),
        name="files.publish",
        arguments=arguments,
        created_at=datetime.now(UTC),
    )


def test_publish_file_returns_governed_artifact_metadata(tmp_path: Path) -> None:
    (tmp_path / "report.csv").write_bytes(b"symbol,score\nAAPL,1\n")
    captured: list[tuple[bytes, str, str]] = []
    tool = FilePublishTool(
        LocalWorkspace(tmp_path),
        lambda payload, name, mime: (
            captured.append((payload, name, mime)) or "artifact://00000000-0000-0000-0000-000000000001"
        ),
        max_bytes=1024,
    )

    result = tool.handle(_call(path="report.csv", display_name="research.csv"))

    assert result.status is ToolCallStatus.EXECUTED
    assert result.metadata["delivery"] is True
    assert result.metadata["file_name"] == "research.csv"
    assert captured == [(b"symbol,score\nAAPL,1\n", "research.csv", "text/csv")]


def test_publish_file_rejects_symlink_and_size_limit(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside-{uuid4().hex}.txt"
    outside.write_bytes(b"secret")
    (tmp_path / "link.txt").symlink_to(outside)
    (tmp_path / "large.bin").write_bytes(b"12345")
    tool = FilePublishTool(LocalWorkspace(tmp_path), lambda *_: "unused", max_bytes=4)

    assert tool.handle(_call(path="link.txt")).metadata["reason"] == "symlink_not_allowed"
    assert tool.handle(_call(path="large.bin")).metadata["reason"] == "file_too_large"
    outside.unlink()


def test_publish_file_rejects_unsafe_display_name(tmp_path: Path) -> None:
    (tmp_path / "report.txt").write_text("ok")
    tool = FilePublishTool(LocalWorkspace(tmp_path), lambda *_: "unused", max_bytes=10)

    try:
        tool.handle(_call(path="report.txt", display_name="../secret.txt"))
    except ValueError as exc:
        assert "safe basename" in str(exc)
    else:
        raise AssertionError("unsafe display name must fail")
