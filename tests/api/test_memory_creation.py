from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from agent_core.domain.agent_tasks import AgentTask
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports import AdministrativeMutationCAS
from zebra_agent_api.memory_creation import create_user_memory
from zebra_agent_api.memory_routes import handle_memory_route
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteRequest

TASK_ID = TaskId(UUID("11111111-1111-4111-8111-111111111111"))
SESSION_ID = SessionId(UUID("22222222-2222-4222-8222-222222222222"))
NOW = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)


class _MemoryStore:
    def __init__(self) -> None:
        self.request = None
        self.authority = None

    def commit_administrative_creation(self, request, *, authority):
        self.request = request
        self.authority = authority
        return SimpleNamespace(receipt=SimpleNamespace(projection_revision=9))


def test_explicit_user_memory_is_confirmed_through_governed_store() -> None:
    memory_store = _MemoryStore()
    task = AgentTask(
        task_id=TASK_ID,
        title="memory source",
        status=SessionStatus.COMPLETED,
        active_segment_id=SESSION_ID,
        current_sequence=7,
        namespace="cloud",
    )
    session = Session(
        session_id=SESSION_ID,
        title="memory source",
        status=SessionStatus.COMPLETED,
        created_at=NOW,
        updated_at=NOW,
        current_sequence=7,
    )
    stores = SimpleNamespace(
        deployment_namespace="test",
        memories=memory_store,
        sessions=SimpleNamespace(get_session=lambda session_id: session),
        tasks=SimpleNamespace(get_task=lambda task_id: task),
    )

    response = create_user_memory(
        stores=stores,
        user_id="user-1",
        payload={
            "operator": "user-1",
            "reason": "added by user",
            "source_task_id": str(TASK_ID),
            "text": "Prefer evidence-first answers.",
        },
    )

    assert response.status_code == 200
    assert response.body["status"] == "confirmed"
    assert memory_store.request.memory.record.text == "Prefer evidence-first answers."
    assert memory_store.request.memory.record.user_id == "user-1"
    assert memory_store.request.memory.record.source_event_start == 8
    assert memory_store.authority == AdministrativeMutationCAS(
        deployment_namespace="test",
        session_id=SESSION_ID,
        expected_stream_revision=7,
    )


def test_explicit_user_memory_requires_existing_source_task() -> None:
    stores = SimpleNamespace(
        deployment_namespace="test",
        memories=_MemoryStore(),
        sessions=SimpleNamespace(get_session=lambda session_id: None),
        tasks=SimpleNamespace(get_task=lambda task_id: None),
    )

    response = create_user_memory(
        stores=stores,
        user_id="user-1",
        payload={
            "operator": "user-1",
            "source_task_id": str(TASK_ID),
            "text": "Remember this.",
        },
    )

    assert response.status_code == 409
    assert response.body["status"] == "memory_creation_source_unavailable"


def test_user_memory_post_route_dispatches_creation() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def create(user_id: str, payload: dict[str, object]) -> ApiResponse:
        calls.append((user_id, payload))
        return ApiResponse(200, {"status": "confirmed"})

    response = handle_memory_route(
        SimpleNamespace(create_user_memory=create),
        RouteRequest(
            method="POST",
            path="/users/user-1/memory",
            body={"text": "Remember this."},
        ),
    )

    assert response == ApiResponse(200, {"status": "confirmed"})
    assert calls == [("user-1", {"text": "Remember this."})]


def test_user_memory_post_rejects_foreign_source_task(monkeypatch) -> None:
    context = HostContextEnvelope(
        grant_id="grant-user-1",
        host_app_id="trench",
        namespace_id="trench-prod",
        workspace_ref="workspace-1",
        resource_refs=(HostResourceRef(type="principal", id="user-1"),),
        scopes=("agent.run",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=60,
            max_model_tokens=1000,
            max_artifact_bytes=1024,
        ),
        origin="https://trench.local",
        policy_version="v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    denied = ApiResponse(404, {"status": "not_found"})
    monkeypatch.setattr(
        "zebra_agent_api.memory_routes.task_access_response",
        lambda app, task_id, host_context: denied,
    )

    response = handle_memory_route(
        SimpleNamespace(create_user_memory=lambda *_: None),
        RouteRequest(
            method="POST",
            path="/users/user-1/memory",
            body={"source_task_id": str(TASK_ID), "text": "Remember this."},
            host_context=context,
        ),
    )

    assert response == denied
