import asyncio
import base64
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import (
    ArtifactId,
    HandoffId,
    SessionId,
    TaskId,
    new_memory_id,
    new_tool_call_id,
)
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_storage import ControlPlaneStores, sqlite_control_plane_stores
from fastapi.testclient import TestClient
from zebra_agent_api import RouteAdapter, RouteRequest, create_app, create_http_app
from zebra_agent_api.session_context_control import SessionContextControlApi
from zebra_agent_api.session_handoff import SessionHandoffApi
from zebra_agent_api.session_streaming import tail_session_events
from zebra_agent_config import load_settings


class _DisconnectedAfterReplay:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1


def test_http_api_and_sse_use_injected_control_plane_stores(tmp_path: Path) -> None:
    control_path = tmp_path / "control.sqlite"
    legacy_path = tmp_path / "legacy.sqlite"
    local = sqlite_control_plane_stores(control_path)
    stores = replace(
        local,
        events=Mock(wraps=local.events),
        sessions=Mock(wraps=local.sessions),
        workspaces=Mock(wraps=local.workspaces),
        tasks=Mock(wraps=local.tasks),
        leases=Mock(wraps=local.leases),
    )
    payload = {
        "prompt": "Keep control-plane state in the injected stores.",
        "title": "Injected storage seam",
        "workspace": str(tmp_path),
        "attachments": [
            {
                "file_name": "authority.txt",
                "media_type": "text/plain",
                "content_base64": base64.b64encode(b"stored on backend B").decode(),
            }
        ],
    }

    with TestClient(create_http_app(legacy_path, stores=stores)) as client:
        created = client.post(
            "/sessions",
            json=payload,
            headers={"Idempotency-Key": "authority-create-1"},
        )
        replayed = client.post(
            "/sessions",
            json=payload,
            headers={"Idempotency-Key": "authority-create-1"},
        )
        assert created.status_code == 201
        assert replayed.json() == created.json()
        session_id = SessionId(UUID(created.json()["session_id"]))
        attachment_id = ArtifactId(UUID(created.json()["attachments"][0]["attachment_id"]))

        fetched = client.get(f"/sessions/{session_id}")
        listed = client.get("/sessions")
        cancelled = client.post(f"/sessions/{session_id}/cancel", json={})

    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Injected storage seam"
    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["session_id"] == str(session_id)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    session = stores.sessions.get_session(session_id)
    assert session is not None
    assert session.status.value == "cancelled"
    assert stores.events.list_for_session(session_id)
    assert stores.workspaces.get_workspace(session_id) is not None
    assert stores.tasks.get_task(TaskId(UUID(str(session_id)))) is not None
    assert (
        stores.idempotency.get(action="session.create", idempotency_key="authority-create-1")
        is not None
    )
    assert stores.artifact_payloads.read_payload_bytes(attachment_id) == b"stored on backend B"

    async def replay() -> list[str]:
        return [
            chunk
            async for chunk in tail_session_events(
                database_path=legacy_path,
                stores=stores,
                session_id=session_id,
                request=_DisconnectedAfterReplay(),  # type: ignore[arg-type]
                after_sequence=-1,
            )
        ]

    assert any('"event_type": "session_created"' in chunk for chunk in asyncio.run(replay()))
    assert stores.events.append.call_count >= 2  # type: ignore[attr-defined]
    assert stores.events.list_for_session.call_count >= 2  # type: ignore[attr-defined]
    assert stores.sessions.save_session.call_count >= 2  # type: ignore[attr-defined]
    assert stores.workspaces.save_workspace.called  # type: ignore[attr-defined]
    assert stores.tasks.get_task.called  # type: ignore[attr-defined]
    assert not legacy_path.exists()
    legacy = sqlite_control_plane_stores(legacy_path)
    assert legacy.events.list_for_session(session_id) == []
    assert legacy.sessions.get_session(session_id) is None
    assert (
        legacy.idempotency.get(action="session.create", idempotency_key="authority-create-1")
        is None
    )
    assert legacy.artifact_payloads.get_payload(attachment_id) is None


def test_api_lifecycle_roots_accept_distinct_authoritative_backend(tmp_path: Path) -> None:
    stores = sqlite_control_plane_stores(tmp_path / "authority.sqlite")
    legacy_path = tmp_path / "legacy.sqlite"

    assert SessionContextControlApi(legacy_path, stores=stores)._stores is stores
    handoff = SessionHandoffApi(legacy_path, stores=stores)
    assert handoff._context_lifecycle is stores.context_lifecycle
    assert handoff._handoffs is stores.handoffs
    assert handoff._effects is stores.effects
    assert not legacy_path.exists()


def test_handoff_and_effect_replay_stay_on_authoritative_backend(tmp_path: Path) -> None:
    authority_path = tmp_path / "authority.sqlite"
    legacy_path = tmp_path / "legacy.sqlite"
    stores = sqlite_control_plane_stores(authority_path)
    source_id = _seed_completed_session(stores, tmp_path)
    effect_identity = EffectIdentity(
        authority_scope_hash="authority",
        tool_name="command.run",
        operation_kind="command.run",
        target_hash="target",
        canonical_effect_hash="effect",
    )
    reservation = stores.effects.reserve(source_id, effect_identity)
    stores.effects.mark_executing(reservation)
    stores.effects.mark_succeeded(
        reservation,
        ToolResult(
            tool_call_id=new_tool_call_id(),
            status=ToolCallStatus.EXECUTED,
            output="done",
        ),
    )
    adapter = RouteAdapter(
        create_app(
            legacy_path,
            settings=load_settings({"ZEBRA_SESSION_HANDOFF_ENABLED": "true"}),
            stores=stores,
        )
    )
    request = RouteRequest(
        method="POST",
        path=f"/sessions/{source_id}/handoff",
        headers={"Idempotency-Key": "authority-handoff-1"},
        body={
            "title": "Authoritative child",
            "objective": "Keep one durable stream",
            "stage_prompt": "Continue from the composed backend",
        },
    )

    created = adapter.handle(request)
    replayed = adapter.handle(request)

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert replayed.body["child_session_id"] == created.body["child_session_id"]
    handoff_id = HandoffId(UUID(str(created.body["handoff_id"])))
    child_id = SessionId(UUID(str(created.body["child_session_id"])))
    assert stores.handoffs.get_handoff(handoff_id) is not None
    dispatch = stores.handoff_dispatch.claim_for_child(
        child_id,
        worker_id="worker-b",
        claimed_at=datetime(2026, 7, 24, 3, 0, tzinfo=UTC),
    )
    assert dispatch is not None
    stores.handoff_dispatch.acknowledge(dispatch.delivery_id, worker_id="worker-b")
    assert stores.effects.terminal_keys(source_id)

    assert not legacy_path.exists()
    legacy = sqlite_control_plane_stores(legacy_path)
    assert legacy.handoffs.get_handoff(handoff_id) is None
    assert legacy.events.list_for_session(child_id) == []
    assert (
        legacy.handoff_dispatch.claim_for_child(
            child_id,
            worker_id="worker-a",
            claimed_at=datetime(2026, 7, 24, 3, 0, tzinfo=UTC),
        )
        is None
    )
    assert legacy.effects.terminal_keys(source_id) == frozenset()


def test_memory_review_stays_on_authoritative_backend(tmp_path: Path) -> None:
    authority_path = tmp_path / "authority.sqlite"
    legacy_path = tmp_path / "legacy.sqlite"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    stores = sqlite_control_plane_stores(authority_path)
    session_id = _seed_completed_session(stores, workspace)
    recorded_at = datetime(2026, 7, 24, 5, 0, tzinfo=UTC)
    candidate = MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=MemoryType.PROCEDURE,
        text="Run the authoritative storage checks.",
        confidence=0.9,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id=str(workspace.resolve()),
        source_session_id=session_id,
        source_event_start=1,
        source_event_end=2,
        created_at=recorded_at,
        updated_at=recorded_at,
    )
    stores.memories.upsert(candidate)

    response = create_app(legacy_path, stores=stores).confirm_session_memory(
        str(session_id),
        str(candidate.memory_id),
        {"operator": "codex", "reason": "verified on backend B"},
    )

    assert response.status_code == 200
    reviewed = stores.memories.get(candidate.memory_id)
    assert reviewed is not None
    assert reviewed.status is MemoryStatus.CONFIRMED
    assert stores.events.list_for_session(session_id)[-1].event_type is (
        EventType.MEMORY_REVIEW_RECORDED
    )
    assert not legacy_path.exists()
    legacy = sqlite_control_plane_stores(legacy_path)
    assert legacy.memories.get(candidate.memory_id) is None
    assert legacy.events.list_for_session(session_id) == []


def _seed_completed_session(
    stores: ControlPlaneStores,
    workspace: Path,
) -> SessionId:
    created_at = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Authoritative source",
            user_input="Complete the first stage.",
            workspace_root=workspace.resolve(),
            created_at=created_at,
        )
    )
    events = (
        *bootstrap.events,
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=created_at,
        ),
    )
    for event in events:
        stores.events.append(event)
    stores.sessions.save_session(rebuild_session(list(events)))
    stores.workspaces.save_workspace(rebuild_workspace(list(events)))
    return bootstrap.session.session_id
