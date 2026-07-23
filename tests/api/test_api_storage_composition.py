import asyncio
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from agent_core.domain.identifiers import SessionId, TaskId
from agent_storage import ControlPlaneStores, sqlite_control_plane_stores
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.session_context_control import SessionContextControlApi
from zebra_agent_api.session_handoff import SessionHandoffApi
from zebra_agent_api.session_streaming import tail_session_events


class _DisconnectedAfterReplay:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1


def test_http_api_and_sse_use_injected_control_plane_stores(tmp_path: Path) -> None:
    control_path = tmp_path / "control.sqlite"
    local = sqlite_control_plane_stores(control_path)
    stores = ControlPlaneStores(
        events=Mock(wraps=local.events),
        sessions=Mock(wraps=local.sessions),
        workspaces=Mock(wraps=local.workspaces),
        tasks=Mock(wraps=local.tasks),
        leases=Mock(wraps=local.leases),
        legacy_database_path=control_path.resolve(),
    )

    with TestClient(create_http_app(control_path, stores=stores)) as client:
        created = client.post(
            "/sessions",
            json={
                "prompt": "Keep control-plane state in the injected stores.",
                "title": "Injected storage seam",
                "workspace": str(tmp_path),
            },
        )
        assert created.status_code == 201
        session_id = SessionId(UUID(created.json()["session_id"]))

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

    async def replay() -> list[str]:
        return [
            chunk
            async for chunk in tail_session_events(
                database_path=control_path,
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


def test_http_api_rejects_partial_split_backend(tmp_path: Path) -> None:
    control_path = tmp_path / "control.sqlite"
    runtime_path = tmp_path / "runtime.sqlite"

    with pytest.raises(ValueError, match="must share database_path"):
        create_http_app(runtime_path, stores=sqlite_control_plane_stores(control_path))

    assert not runtime_path.exists()


def test_http_api_rejects_stores_without_legacy_path_identity(tmp_path: Path) -> None:
    control_path = tmp_path / "control.sqlite"
    local = sqlite_control_plane_stores(control_path)
    unidentified = ControlPlaneStores(
        events=local.events,
        sessions=local.sessions,
        workspaces=local.workspaces,
        tasks=local.tasks,
        leases=local.leases,
    )

    with pytest.raises(ValueError, match="must share database_path"):
        create_http_app(control_path, stores=unidentified)


def test_api_lifecycle_roots_reject_partial_split_backend(tmp_path: Path) -> None:
    control_path = tmp_path / "control.sqlite"
    runtime_path = tmp_path / "runtime.sqlite"
    stores = sqlite_control_plane_stores(control_path)

    with pytest.raises(ValueError, match="must share database_path"):
        SessionContextControlApi(runtime_path, stores=stores)
    with pytest.raises(ValueError, match="must share database_path"):
        SessionHandoffApi(runtime_path, stores=stores)

    assert not runtime_path.exists()
