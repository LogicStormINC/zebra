from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_storage import SQLiteArtifactPayloadStore
from zebra_agent_worker.task_recovery import recover_task


def test_worker_recovery_preserves_persisted_model_selection(tmp_path: Path) -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Selected model task",
            user_input="Continue the task",
            workspace_root=tmp_path,
            model_id="qwen-native",
        )
    )

    recovered = recover_task(
        list(bootstrap.events),
        workspace=rebuild_workspace(list(bootstrap.events)),
        fallback_title="fallback",
        attachment_store=SQLiteArtifactPayloadStore(tmp_path / "sessions.sqlite"),
    )

    assert recovered.model_id == "qwen-native"


def test_handoff_segment_uses_root_task_model_selection(tmp_path: Path) -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Handoff segment",
            user_input="Continue from the checkpoint",
            workspace_root=tmp_path,
        )
    )

    recovered = recover_task(
        list(bootstrap.events),
        workspace=rebuild_workspace(list(bootstrap.events)),
        fallback_title="fallback",
        attachment_store=SQLiteArtifactPayloadStore(tmp_path / "sessions.sqlite"),
        task_model_id="deepseek-text",
    )

    assert recovered.model_id == "deepseek-text"
