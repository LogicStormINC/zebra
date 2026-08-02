from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_storage import SQLiteArtifactPayloadStore
from zebra_agent_worker.task_recovery import persisted_task_model_id, recover_task


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


def test_worker_handoff_recovery_keeps_the_same_persisted_model_id(tmp_path: Path) -> None:
    root = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Root task",
            user_input="Root request",
            workspace_root=tmp_path,
            model_id="qwen-native",
        )
    )
    child = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Child task",
            user_input="Handoff request",
            workspace_root=tmp_path,
            model_id="qwen-native",
        )
    )

    selected = persisted_task_model_id([root.events[2], child.events[2]])

    assert selected == "qwen-native"


def test_worker_fails_closed_on_root_child_model_selection_conflict(tmp_path: Path) -> None:
    root = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Root task",
            user_input="Root request",
            workspace_root=tmp_path,
            model_id="qwen-native",
        )
    )
    child = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Child task",
            user_input="Handoff request",
            workspace_root=tmp_path,
            model_id="deepseek-text",
        )
    )

    with pytest.raises(ValueError, match="model selection drift"):
        persisted_task_model_id([root.events[2], child.events[2]])
