from pathlib import Path

from agent_core.domain.events import EventType
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.app import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_root_task_persists_explicit_goal_bound_contract(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    response = RouteAdapter(create_app(database, settings=_settings(database))).handle(
        RouteRequest(
            method="POST",
            path="/tasks",
            body={
                "title": "Daily journal",
                "prompt": "Continue today's journal.",
                "workspace": str(tmp_path),
                "goal_binding": "goal_bound",
                "goal_text": "Maintain today's daily journal.",
            },
        )
    )

    assert response.status_code == 201
    task_id = response.body["task_id"]
    events = SQLiteEventStore(database).list_for_session(task_id)
    assert [event.event_type for event in events] == [
        EventType.SESSION_CREATED,
        EventType.TASK_GOAL_SET,
        EventType.USER_MESSAGE_RECEIVED,
        EventType.TASK_PREPARED,
    ]
    assert [event.sequence for event in events] == [0, 1, 2, 3]
    assert events[1].payload["goal_text"] == "Maintain today's daily journal."
    assert events[-1].payload["goal_binding"] == "goal_bound"
    assert events[-1].payload["goal_text"] == "Maintain today's daily journal."

    session = SQLiteProjectionStore(database).get_session(task_id)
    assert session is not None
    assert session.active_goal is not None
    assert session.active_goal.text == "Maintain today's daily journal."


def test_root_task_rejects_goal_bound_without_goal_text(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    response = RouteAdapter(create_app(database, settings=_settings(database))).handle(
        RouteRequest(
            method="POST",
            path="/tasks",
            body={
                "prompt": "Continue today's journal.",
                "workspace": str(tmp_path),
                "goal_binding": "goal_bound",
            },
        )
    )

    assert response.status_code == 400
    assert "goal_text" in response.body["reason"]


def test_task_message_revises_the_durable_goal_before_the_turn(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    routes = RouteAdapter(create_app(database, settings=_settings(database)))
    created = routes.handle(
        RouteRequest(
            method="POST",
            path="/tasks",
            body={
                "title": "Daily journal",
                "prompt": "Continue today's journal.",
                "workspace": str(tmp_path),
                "goal_binding": "goal_bound",
                "goal_text": "Maintain today's daily journal.",
            },
        )
    )
    assert created.status_code == 201
    task_id = created.body["task_id"]

    appended = routes.handle(
        RouteRequest(
            method="POST",
            path=f"/tasks/{task_id}/messages",
            body={
                "content": "Exclude the draft imported this morning.",
                "goal_text": "Maintain today's daily journal without the morning draft.",
            },
        )
    )

    assert appended.status_code == 201
    events = SQLiteEventStore(database).list_for_session(task_id)
    assert [event.event_type for event in events[-2:]] == [
        EventType.TASK_GOAL_REVISED,
        EventType.USER_MESSAGE_RECEIVED,
    ]
    assert [event.sequence for event in events] == [0, 1, 2, 3, 4, 5]
    session = SQLiteProjectionStore(database).get_session(task_id)
    assert session is not None and session.active_goal is not None
    assert session.active_goal.version == 2
    assert session.active_goal.text == "Maintain today's daily journal without the morning draft."


def _settings(database: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )
