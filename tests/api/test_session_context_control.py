from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app


def test_session_context_route_compacts_and_inspects_durable_capsule(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database, tmp_path)
    adapter = RouteAdapter(create_app(database))

    compacted = adapter.handle(
        RouteRequest(method="POST", path=f"/sessions/{session_id}/context/compact")
    )
    inspected = adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{session_id}/context")
    )

    assert compacted.status_code == 200
    assert compacted.body["status"] == "compacted"
    assert compacted.body["capsule"]["objective"] == "Finish the task."
    assert inspected.status_code == 200
    assert inspected.body["compaction_count"] == 1
    assert inspected.body["occupancy"]["categories"]["capsule"] > 0
    assert inspected.body["state"]["historical_capsules"]
    assert inspected.body["latest"]["capsule"]["source_hash"]
    assert inspected.body["continuation"] == {
        "mode": "capsule_fallback",
        "provider_native": False,
        "authority": "session_events_and_capsule_artifact",
        "reason": None,
        "artifact_id": None,
    }


def test_context_preview_focus_and_historical_recovery(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database, tmp_path)
    adapter = RouteAdapter(create_app(database))

    preview = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/context/compact",
            body={
                "preview": True,
                "focus": "preserve auth decisions",
                "through_sequence": 1,
            },
        )
    )
    assert preview.body["status"] == "preview"
    assert preview.body["capsule"]["constraints"][-1] == (
        "Compaction focus: preserve auth decisions"
    )
    assert preview.body["capsule"]["recent_exact_tail_refs"]
    assert adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{session_id}/context")
    ).body["compaction_count"] == 0

    compacted = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/context/compact",
            body={"focus": "preserve auth decisions"},
        )
    )
    capsule_id = compacted.body["capsule"]["capsule_id"]
    recovered = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/context/recover",
            body={"capsule_id": capsule_id},
        )
    )

    assert recovered.status_code == 200
    assert recovered.body["status"] == "recovered"
    assert recovered.body["capsule"]["capsule_id"] == capsule_id


def test_compaction_preserves_structured_work_and_permission_boundaries(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sessions.sqlite"
    session_id = _seed_ready_session(database, tmp_path)
    events = SQLiteEventStore(database)
    projections = SQLiteProjectionStore(database)
    session = projections.get_session(session_id)
    assert session is not None
    additions = (
        SessionEvent.create(
            session_id=session_id,
            sequence=session.current_sequence + 1,
            event_type=EventType.PLAN_UPDATED,
            actor=EventActor.HARNESS,
            payload={
                "steps": [
                    {"step_id": "done", "content": "inspect root cause", "status": "completed"},
                    {"step_id": "next", "content": "run acceptance", "status": "in_progress"},
                    {"step_id": "no", "content": "rewrite runtime", "status": "cancelled"},
                ]
            },
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=session.current_sequence + 2,
            event_type=EventType.POLICY_DECISION_MADE,
            actor=EventActor.POLICY,
            payload={"decision": "production_write_requires_approval"},
        ),
    )
    for event in additions:
        events.append(event)
        session = apply_event(session, event)
    projections.save_session(session)

    response = RouteAdapter(create_app(database)).handle(
        RouteRequest(method="POST", path=f"/sessions/{session_id}/context/compact")
    )

    assert response.status_code == 200
    capsule = response.body["capsule"]
    assert capsule["completed_actions"] == ["inspect root cause"]
    assert capsule["pending_actions"] == ["run acceptance"]
    assert capsule["rejected_approaches"] == ["rewrite runtime"]
    assert capsule["permission_boundaries"] == [
        "policy_decision_made:production_write_requires_approval"
    ]
    assert capsule["immediate_next"] == "run acceptance"


def _seed_ready_session(database: Path, workspace: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Context control",
            user_input="Finish the task.",
            workspace_root=workspace.resolve(),
        )
    )
    store = SQLiteEventStore(database)
    for event in bootstrap.events:
        store.append(event)
    SQLiteProjectionStore(database).save_session(bootstrap.session)
    return bootstrap.session.session_id
