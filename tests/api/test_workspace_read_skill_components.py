from __future__ import annotations

from datetime import UTC, datetime

from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from zebra_agent_api.workspace_read import serialize_workspace_projection


def _projection(skill_components: tuple[str, ...] | None):
    event = SessionEvent.create(
        session_id="00000000-0000-0000-0000-000000000002",
        sequence=0,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "Skill projection",
            "user_input": "Continue",
            "workspace_root": "/tmp/skill-projection",
        },
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    projection = rebuild_workspace([event])
    if skill_components is None:
        return projection
    return projection.model_copy(update={"skill_components": skill_components})


def test_serialize_workspace_projection_emits_skill_components() -> None:
    body = serialize_workspace_projection(_projection(("Review", "evidence")))
    assert body is not None
    assert body["skill_components"] == ["Review", "evidence"]


def test_serialize_workspace_projection_omits_missing_skill_components() -> None:
    body = serialize_workspace_projection(_projection(None))
    assert body is not None
    assert "skill_components" not in body
