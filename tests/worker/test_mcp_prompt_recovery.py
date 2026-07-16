from pathlib import Path

import agent_runtime
import pytest
from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
    build_mcp_prompt_attachment,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_storage import SQLiteArtifactPayloadStore, store_initial_text_attachments
from zebra_agent_worker.task_recovery import recover_task


def test_worker_recovers_only_captured_prompt_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Recover prompt",
            user_input="Use captured context",
            workspace_root=tmp_path,
            network_profile="mcp-proxy-only",
        )
    )
    attachment = build_mcp_prompt_attachment(
        server_name="offline",
        prompt_id="mcp-prompt:" + "3" * 32,
        argument_names=("topic",),
        messages=(("user", "CAPTURED_PROMPT_BYTES"),),
    )
    events, _ = store_initial_text_attachments(
        SQLiteArtifactPayloadStore(database),
        bootstrap.events,
        (attachment,),
    )
    monkeypatch.setattr(
        agent_runtime,
        "resolve_mcp_prompt",
        lambda *_args: (_ for _ in ()).throw(AssertionError("MCP must not be read")),
    )

    recovered = recover_task(
        list(events),
        workspace=rebuild_workspace(list(events)),
        fallback_title="fallback",
        attachment_store=SQLiteArtifactPayloadStore(database),
    )

    assert len(recovered.attachments) == 1
    assert recovered.attachments[0].source_type == "mcp_prompt"
    assert recovered.attachments[0].source_argument_names == ("topic",)
    assert "CAPTURED_PROMPT_BYTES" in recovered.attachments[0].text
