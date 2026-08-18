"""CLOUD-WORKSPACE-CP-API-01 route and payload coverage."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_core.domain.workspace_control import (
    WorkspaceId,
    WorkspaceInstance,
    WorkspaceLifecycleState,
    WorkspaceSource,
)
from zebra_agent_api import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


class FakeWorkspaceStore:
    def __init__(self) -> None:
        self.instances: dict[UUID, WorkspaceInstance] = {}
        self.keys: list[str] = []

    def create_pending(
        self,
        source: WorkspaceSource,
        *,
        workspace_id: WorkspaceId,
        quota_bytes: int,
        owner_session_id: UUID | None,
        idempotency_key: str,
    ) -> tuple[WorkspaceInstance, Any]:
        self.keys.append(idempotency_key)
        if workspace_id not in self.instances:
            self.instances[workspace_id] = WorkspaceInstance(
                workspace_id=workspace_id,
                deployment_namespace="cloud-a",
                source=source,
                state=WorkspaceLifecycleState.PENDING,
                quota_bytes=quota_bytes,
            )
        return self.instances[workspace_id], None

    def get(self, workspace_id: WorkspaceId) -> WorkspaceInstance | None:
        return self.instances.get(workspace_id)


def _settings(database_path: Any) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


def _app(tmp_path: Any, store: FakeWorkspaceStore | None) -> Any:
    return create_app(
        tmp_path / "api.sqlite",
        settings=_settings(tmp_path),
        workspace_control_store=store,
    )


def _source_payload() -> dict[str, object]:
    return {
        "kind": "git_repository",
        "locator": "https://git.example/zebra/repo",
        "pinned_revision": "abc123",
    }


def test_create_workspace_submits_a_pending_command(tmp_path: Any) -> None:
    store = FakeWorkspaceStore()
    adapter = RouteAdapter(_app(tmp_path, store))
    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/workspaces",
            headers={},
            body={
                "source": _source_payload(),
                "quota_bytes": 1048576,
                "idempotency_key": "provision-1",
            },
        )
    )
    assert response.status_code == 201
    assert response.body["state"] == "pending"
    assert response.body["workspace_uri"].startswith("workspace://")
    assert store.keys == ["provision-1"]


def test_get_workspace_reads_the_projection(tmp_path: Any) -> None:
    store = FakeWorkspaceStore()
    adapter = RouteAdapter(_app(tmp_path, store))
    created = adapter.handle(
        RouteRequest(
            method="POST",
            path="/workspaces",
            headers={},
            body={
                "source": _source_payload(),
                "quota_bytes": 1048576,
                "idempotency_key": "provision-2",
            },
        )
    )
    fetched = adapter.handle(
        RouteRequest(
            method="GET",
            path=f"/workspaces/{created.body['workspace_id']}",
            headers={},
            body=None,
        )
    )
    assert fetched.status_code == 200
    assert fetched.body["state"] == "pending"
    assert fetched.body["source_kind"] == "git_repository"
    missing = adapter.handle(
        RouteRequest(method="GET", path=f"/workspaces/{UUID(int=1)}", headers={}, body=None)
    )
    assert missing.status_code == 404


def test_workspace_routes_fail_closed_without_the_control_plane(tmp_path: Any) -> None:
    adapter = RouteAdapter(_app(tmp_path, None))
    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/workspaces",
            headers={},
            body={
                "source": _source_payload(),
                "quota_bytes": 1048576,
                "idempotency_key": "provision-3",
            },
        )
    )
    assert response.status_code == 400
    assert "cloud" in str(response.body["reason"])


def test_create_session_binds_a_workspace_source(tmp_path: Any) -> None:
    store = FakeWorkspaceStore()
    adapter = RouteAdapter(_app(tmp_path, store))
    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/sessions",
            headers={"Idempotency-Key": "session-ws-1"},
            body={
                "prompt": "run inside the provisioned workspace",
                "workspace_source": _source_payload(),
            },
        )
    )
    assert response.status_code == 201
    assert str(response.body["workspace"]).startswith("workspace://")
    assert response.body["status"] == "ready"
    assert len(store.instances) == 1


def test_create_session_rejects_source_without_the_control_plane(tmp_path: Any) -> None:
    adapter = RouteAdapter(_app(tmp_path, None))
    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/sessions",
            headers={"Idempotency-Key": "session-ws-2"},
            body={"prompt": "x", "workspace_source": _source_payload()},
        )
    )
    assert response.status_code == 400
