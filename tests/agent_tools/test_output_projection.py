from agent_tools import ToolOutputProjector


def test_tool_output_projector_persists_full_output_and_bounds_model_view() -> None:
    persisted: list[tuple[str, str]] = []
    projector = ToolOutputProjector(
        lambda content, name: (
            persisted.append((content, name)) or "file:///artifacts/command.txt"
        ),
        max_model_characters=256,
    )

    projected = projector.project(
        stdout="head\n" + "x" * 500 + "\ntail",
        stderr="failure detail",
        artifact_name="command.txt",
    )

    assert persisted == [
        ("[stdout]\nhead\n" + "x" * 500 + "\ntail\n\n[stderr]\nfailure detail", "command.txt")
    ]
    assert "head" in projected.model_output
    assert "tail" in projected.model_output
    assert "middle omitted" in projected.model_output
    assert "file:///artifacts/command.txt" in projected.model_output
    assert projected.metadata["artifact_uri"] == "file:///artifacts/command.txt"
    assert projected.metadata["output_truncated"] is True
    assert projected.metadata["output_size_bytes"] > 500
    envelope = projected.metadata["output_envelope"]
    assert isinstance(envelope, dict)
    assert envelope["artifact_uri"] == "file:///artifacts/command.txt"
    assert envelope["preview_head"].startswith("[stdout]\nhead")
    assert envelope["preview_tail"].endswith("failure detail")
    assert envelope["original_bytes"] == projected.metadata["output_size_bytes"]
    assert envelope["checksum"] == projected.metadata["output_sha256"]


def test_tool_output_projector_keeps_small_stdout_and_stderr_exact() -> None:
    projector = ToolOutputProjector(lambda content, name: "artifact://small")

    projected = projector.project(
        stdout="ok",
        stderr="warning",
        artifact_name="tests.txt",
    )

    assert projected.model_output == "[stdout]\nok\n\n[stderr]\nwarning"
    assert projected.metadata["output_truncated"] is False


def test_projected_ranges_match_actual_snapshot_text_and_reach_model() -> None:
    import json

    from agent_core.domain.identifiers import new_tool_call_id
    from agent_core.domain.tools import ToolCallStatus, ToolResult
    from agent_core.harness.model_step_support import tool_result_content

    content = "前文" + "0123456789" * 70 + "结尾"
    projected = ToolOutputProjector(lambda *_: "artifact://snapshot", max_model_characters=256)
    result = projected.project_text(content, artifact_name="snapshot.txt")
    coverage = result.metadata["output_coverage"]
    (start, head_end), (tail_start, end) = coverage["included_ranges"]
    assert start == 0 and end == len(content)
    marker = "\n\n[... middle omitted from model context ...]\n\n"
    assert result.model_output == (
        content[start:head_end]
        + marker
        + content[tail_start:end]
        + "\n\n[Complete output: artifact://snapshot]"
    )
    assert head_end < tail_start
    observation = json.loads(
        tool_result_content(
            ToolResult(
                tool_call_id=new_tool_call_id(),
                status=ToolCallStatus.EXECUTED,
                output=result.model_output,
                metadata={"coverage": {"business": True}, **result.metadata},
            )
        )
    )
    assert observation["output_coverage"] == coverage
    assert observation["coverage"] == {"business": True}
    small = projected.project(stdout="hello", stderr="", artifact_name="small.txt")
    assert small.metadata["output_coverage"] == {
        "total_characters": 14,
        "included_ranges": [[9, 14]],
    }
    transformed = projected.project_text(
        "original", artifact_name="small.txt", small_output="other"
    )
    assert transformed.metadata["output_coverage"]["included_ranges"] == []
