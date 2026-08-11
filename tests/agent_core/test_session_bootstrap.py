from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventType
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_profiles import ToolProfile


def test_session_bootstrap_service_builds_ready_session_events() -> None:
    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Bootstrap task",
            user_input="Inspect the repository.",
            workspace_root=Path("/tmp/bootstrap"),
            policy_profile="workspace_write",
        )
    )

    assert [event.event_type for event in result.events] == [
        EventType.SESSION_CREATED,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
    ]
    assert result.events[1].payload == {"content": "Inspect the repository."}
    assert result.events[2].payload == {
        "title": "Bootstrap task",
        "user_input": "Inspect the repository.",
        "workspace_root": "/tmp/bootstrap",
        "policy_profile": "workspace_write",
        "tool_profile": ToolProfile.GENERAL,
        "network_profile": "none",
        "network_allowlist": [],
        "mcp_allowlist": [],
        "skill_components": [],
        "max_attempts": 1,
        "max_model_calls": None,
        "max_tool_calls": None,
    }
    assert result.session.status is SessionStatus.READY
    assert result.session.current_sequence == 2


def test_session_bootstrap_persists_explicit_history_scope() -> None:
    session_id = "00000000-0000-0000-0000-000000000001"

    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Scoped history",
            user_input="Continue the prior task.",
            workspace_root=Path("/tmp/bootstrap"),
            history_session_ids=(session_id,),
        )
    )

    assert result.events[2].payload["history_session_ids"] == [session_id]


def test_session_bootstrap_persists_only_secret_free_host_context() -> None:
    context = HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="trench",
        namespace_id="tenant-a",
        workspace_ref="workspace-a",
        resource_refs=(HostResourceRef(type="trench.event", id="evt-1"),),
        scopes=("event.read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300,
            max_model_tokens=100_000,
            max_artifact_bytes=10_485_760,
        ),
        origin="https://trench.example.com",
        policy_version="policy-v1",
    )
    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Host task",
            user_input="Read the selected event",
            workspace_root=Path("/tmp/host-task"),
            host_context=context,
        )
    )

    persisted = result.events[2].payload["host_context"]
    assert persisted["grant_id"] == "grant-1"
    assert persisted["resource_refs"] == (
        {"resource_type": "trench.event", "resource_id": "evt-1"},
    )
    assert "authorization" not in str(persisted).lower()
