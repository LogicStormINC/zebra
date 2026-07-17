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
