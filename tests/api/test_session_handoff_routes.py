from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_api import RouteAdapter, RouteRequest, create_app

NOW = datetime(2026, 7, 18, tzinfo=UTC)


def test_handoff_routes_create_inspect_lineage_and_idempotent_replay(tmp_path: Path) -> None:
    database = tmp_path / "handoff.db"
    source = _seed_completed(database, tmp_path)
    adapter = RouteAdapter(create_app(database))
    request = RouteRequest(
        method="POST",
        path=f"/sessions/{source}/handoff",
        headers={"Idempotency-Key": "stage-two", "Authorization": "Bearer secret"},
        body={
            "title": "Stage two",
            "objective": "Finish operator surfaces",
            "stage_prompt": "Continue with CLI integration",
            "completed_work": ["core merged"],
            "pending_work": ["CLI"],
        },
    )

    created = adapter.handle(request)
    replay = adapter.handle(request)
    conflicting = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{source}/handoff",
            headers=request.headers,
            body={**request.body, "objective": "Different objective"},
        )
    )
    inspected = adapter.handle(
        RouteRequest(method="GET", path=f"/handoffs/{created.body['handoff_id']}")
    )
    lineage = adapter.handle(
        RouteRequest(method="GET", path=f"/sessions/{created.body['child_session_id']}/lineage")
    )

    assert created.status_code == 201
    assert replay.status_code == 200
    assert replay.body["child_session_id"] == created.body["child_session_id"]
    assert replay.body["idempotent_replay"] is True
    assert conflicting.status_code == 409
    assert conflicting.body["status"] == "handoff_idempotency_conflict"
    assert inspected.body["checksum"] == created.body["checksum"]
    assert [stage["stage_index"] for stage in lineage.body["stages"]] == [0, 1]
    child_events = SQLiteEventStore(database).list_for_session(
        SessionId(UUID(str(created.body["child_session_id"])))
    )
    assert child_events[2].payload["actor_kind"] == "operator"
    assert "secret" not in str(created.body)


def test_preview_rejects_unsafe_boundary_and_clients_cannot_forge_contracts(
    tmp_path: Path,
) -> None:
    database = tmp_path / "handoff.db"
    source = _seed_completed(database, tmp_path)
    adapter = RouteAdapter(create_app(database))
    body = {
        "title": "Stage two",
        "objective": "Continue",
        "stage_prompt": "Continue safely",
    }
    forged = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{source}/handoff",
            headers={"Idempotency-Key": "forged"},
            body={**body, "checksum": "client-value"},
        )
    )
    preview = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{source}/handoff/preview",
            body=body,
        )
    )

    assert forged.status_code == 400
    assert preview.status_code == 200
    assert preview.body["status"] == "preview"
    assert "provider-private continuation" in preview.body["envelope"]["known_omissions"][0]


def _seed_completed(database: Path, workspace: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Source",
            user_input="Complete stage one",
            workspace_root=workspace.resolve(),
            created_at=NOW,
        )
    )
    events = [
        *bootstrap.events,
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    ]
    event_store = SQLiteEventStore(database)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(events))
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(events))
    return bootstrap.session.session_id
