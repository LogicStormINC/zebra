from datetime import UTC, datetime
from pathlib import Path

import agent_runtime
import pytest
from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
    build_mcp_prompt_attachment,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.context_capsule import ContextCapsule, PendingToolState
from agent_core.domain.events import EventActor, EventType, SessionEvent
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
            history_session_ids=("00000000-0000-0000-0000-000000000001",),
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
    assert recovered.history_session_ids == (
        "00000000-0000-0000-0000-000000000001",
    )


def test_worker_reinjects_latest_durable_context_capsule(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Recover context",
            user_input="Finish the refactor",
            workspace_root=tmp_path,
        )
    )
    events = list(bootstrap.events)
    capsule = ContextCapsule(
        capsule_id="ctxcap-123",
        objective="Finish the refactor",
        constraints=("Keep compatibility",),
        decisions=("Use the existing adapter",),
        plan=("Run focused tests",),
        pending_tools=(
            PendingToolState(call_id="call-1", name="tests.run", arguments={"preset": "test"}),
        ),
        artifact_refs=("file:///tmp/test-output.txt",),
        immediate_next="Run focused tests",
        source_hash="a" * 64,
        confidence=0.9,
        created_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
    )
    events.append(
        SessionEvent.create(
            session_id=events[0].session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.CONTEXT_COMPACTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "before_tokens": 100,
                "after_tokens": 50,
                "removed_message_count": 2,
                "retained_message_count": 3,
                "within_budget": True,
                "provenance": "test",
                "capsule": capsule.model_dump(mode="json"),
            },
            created_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        )
    )

    recovered = recover_task(
        events,
        workspace=rebuild_workspace(events),
        fallback_title="fallback",
        attachment_store=SQLiteArtifactPayloadStore(database),
    )

    assert recovered.runtime_evidence[0].summary == "Finish the refactor"
    assert recovered.runtime_evidence[0].metadata is not None
    assert recovered.runtime_evidence[0].metadata["capsule_id"] == "ctxcap-123"
    assert recovered.runtime_evidence[0].metadata["pending_tools"] == [
        {"call_id": "call-1", "name": "tests.run", "arguments": {"preset": "test"}}
    ]


def test_worker_recovery_carries_skill_components_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Recover skills",
            user_input="Continue with the skill set",
            workspace_root=tmp_path,
        )
    )
    events = list(bootstrap.events)
    workspace = rebuild_workspace(events).model_copy(
        update={"skill_components": ("Review", "evidence")}
    )

    recovered = recover_task(
        events,
        workspace=workspace,
        fallback_title="fallback",
        attachment_store=SQLiteArtifactPayloadStore(database),
    )

    assert recovered.skill_components == ("Review", "evidence")
