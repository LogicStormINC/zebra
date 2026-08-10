from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.plans import PlanStepStatus
from agent_storage import SQLiteAgentTaskStore, SQLiteEventStore, SQLiteProjectionStore

NOW = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)


def test_stable_task_projects_root_goal_and_latest_plan(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Stable goal",
            user_input="PRIVATE compiled context and instructions.",
            public_content="Identify the causes of recent repeated losses.",
            workspace_root=tmp_path,
            plan_required=True,
            created_at=NOW,
        )
    )
    events = [
        *bootstrap.events,
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": "Exclude the CICC account for now."},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.PLAN_UPDATED,
            actor=EventActor.HARNESS,
            payload={
                "steps": [
                    {
                        "step_id": "compare",
                        "content": "Compare recent journals",
                        "status": "in_progress",
                    }
                ]
            },
            created_at=NOW,
        ),
    ]
    event_store = SQLiteEventStore(database)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(events))

    task = SQLiteAgentTaskStore(database).ensure_for_session(bootstrap.session.session_id)

    assert task.goal == "Identify the causes of recent repeated losses."
    assert task.plan_required is True
    assert task.task_plan.steps[0].step_id == "compare"
    assert task.task_plan.steps[0].status is PlanStepStatus.IN_PROGRESS


def test_stable_task_uses_title_for_legacy_projection_without_events(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Legacy projected task",
            user_input="Unavailable legacy input",
            workspace_root=tmp_path,
            created_at=NOW,
        )
    )
    SQLiteProjectionStore(database).save_session(bootstrap.session)

    task = SQLiteAgentTaskStore(database).ensure_for_session(bootstrap.session.session_id)

    assert task.goal == "Legacy projected task"
    assert task.plan_required is False
