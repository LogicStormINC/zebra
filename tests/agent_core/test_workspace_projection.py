from datetime import UTC, datetime

import pytest
from agent_core.application.workspace_projection import (
    WorkspaceProjectionError,
    rebuild_workspace,
)
from agent_core.contracts.events import EventPayloadValidationError
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.workspaces import WorkspaceStatus


def test_rebuild_workspace_projects_workspace_lifecycle() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 29, 18, 0, tzinfo=UTC)
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "Workspace Projection"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Workspace Projection",
                "user_input": "continue",
                "workspace_root": "/tmp/workspace-projection",
                "policy_profile": "workspace_write",
                "tool_profile": "general",
            },
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.APPROVAL_REQUESTED,
            actor=EventActor.POLICY,
            payload={
                "attempt_number": 1,
                "tool_name": "mcp.github.create_pull_request",
                "reason": "approval needed",
                "policy_profile": "full_access",
            },
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=4,
            event_type=EventType.APPROVAL_GRANTED,
            actor=EventActor.USER,
            payload={"operator": "alice"},
            created_at=created_at,
        ),
    ]

    projection = rebuild_workspace(events)

    assert projection.session_id == session_id
    assert projection.workspace_root == "/tmp/workspace-projection"
    assert projection.policy_profile == "workspace_write"
    assert projection.tool_profile is ToolProfile.GENERAL
    assert projection.status is WorkspaceStatus.RUNNING
    assert projection.current_sequence == 4
    assert projection.last_attempt_number == 1


def test_rebuild_workspace_requires_task_prepared_event() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 29, 18, 15, tzinfo=UTC)
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "Missing Workspace"},
            created_at=created_at,
        )
    ]

    with pytest.raises(
        WorkspaceProjectionError,
        match="event stream does not contain task_prepared",
    ):
        rebuild_workspace(events)


def test_rebuild_workspace_recovers_legacy_session_as_coding() -> None:
    created_at = datetime(2026, 6, 29, 18, 20, tzinfo=UTC)
    prepared = SessionEvent.create(
        session_id=new_session_id(),
        sequence=0,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "Legacy workspace",
            "user_input": "continue",
            "workspace_root": "/tmp/legacy-workspace",
        },
        created_at=created_at,
    )

    assert rebuild_workspace([prepared]).tool_profile is ToolProfile.CODING


def test_rebuild_workspace_rejects_unknown_tool_profile() -> None:
    with pytest.raises(EventPayloadValidationError, match="invalid payload"):
        SessionEvent.create(
            session_id=new_session_id(),
            sequence=0,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Invalid workspace",
                "user_input": "continue",
                "workspace_root": "/tmp/invalid-workspace",
                "tool_profile": "unknown",
            },
        )


def test_rebuild_workspace_tracks_suspend_snapshot_and_resume_restore() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 29, 18, 30, tzinfo=UTC)
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.USER,
            payload={"title": "Suspend Workspace"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Suspend Workspace",
                "user_input": "continue",
                "workspace_root": "/tmp/workspace-before-suspend",
                "policy_profile": "workspace_write",
            },
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.SESSION_SUSPENDED,
            actor=EventActor.SYSTEM,
            payload={
                "runtime_name": "local",
                "snapshot_id": "snap-001",
                "snapshot_path": "/tmp/snapshots/snap-001",
            },
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_RESUMED,
            actor=EventActor.SYSTEM,
            payload={
                "runtime_name": "local",
                "snapshot_id": "snap-001",
                "workspace_root": "/tmp/workspace-restored",
            },
            created_at=created_at,
        ),
    ]

    projection = rebuild_workspace(events)

    assert projection.status is WorkspaceStatus.PREPARED
    assert projection.workspace_root == "/tmp/workspace-restored"
    assert projection.runtime_name == "local"
    assert projection.snapshot_id is None
    assert projection.snapshot_path is None
