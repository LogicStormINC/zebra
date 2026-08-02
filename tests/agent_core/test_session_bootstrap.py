from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventType
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
        "preapproved_readonly_tools": [],
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


def test_session_bootstrap_persists_explicit_model_catalog_id() -> None:
    result = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Selected model",
            user_input="Use the selected runtime model",
            workspace_root=Path("/tmp/bootstrap"),
            model_id="qwen-native",
        )
    )

    assert result.events[2].payload["model_id"] == "qwen-native"
