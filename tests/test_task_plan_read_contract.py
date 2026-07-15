from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.plans import PlanStep, PlanStepStatus, SessionPlan
from agent_core.domain.sessions import Session
from agent_storage import SQLiteProjectionStore
from zebra_agent_api import create_app
from zebra_agent_cli.cli import execute


def test_api_and_cli_expose_the_same_durable_task_plan(tmp_path: Path) -> None:
    database_path = tmp_path / "task-plan.sqlite"
    updated_at = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    session = Session.create(title="Plan", created_at=updated_at).model_copy(
        update={
            "task_plan": SessionPlan(
                steps=(
                    PlanStep(
                        step_id="research",
                        content="Collect the source material",
                        status=PlanStepStatus.COMPLETED,
                    ),
                    PlanStep(
                        step_id="draft",
                        content="Draft the operator brief",
                        status=PlanStepStatus.IN_PROGRESS,
                    ),
                ),
                updated_at=updated_at,
            )
        }
    )
    SQLiteProjectionStore(database_path).save_session(session)

    expected = session.task_plan.to_mapping()
    api_plan = create_app(database_path).get_session(str(session.session_id)).body["task_plan"]
    cli_plan = execute(
        ["inspect", str(session.session_id), "--database", str(database_path)]
    ).payload["task_plan"]

    assert api_plan == expected
    assert cli_plan == expected


def test_empty_task_plan_is_absent_from_api_and_cli(tmp_path: Path) -> None:
    database_path = tmp_path / "empty-task-plan.sqlite"
    session = Session.create(title="No plan")
    SQLiteProjectionStore(database_path).save_session(session)

    api_payload = create_app(database_path).get_session(str(session.session_id)).body
    cli_payload = execute(
        ["inspect", str(session.session_id), "--database", str(database_path)]
    ).payload

    assert "task_plan" not in api_payload
    assert "task_plan" not in cli_payload
