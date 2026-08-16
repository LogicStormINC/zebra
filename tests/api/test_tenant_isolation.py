"""Cross-tenant isolation matrix for session-scoped API routes."""

from __future__ import annotations

from pathlib import Path

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_storage import sqlite_control_plane_stores
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.responses import ApiResponse


def _host_context(namespace_id: str) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id=f"grant-{namespace_id}",
        host_app_id=f"host-{namespace_id}",
        namespace_id=namespace_id,
        workspace_ref="workspace://unit",
        resource_refs=(HostResourceRef(type="trench.event", id="evt-1"),),
        scopes=("session.write",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=3600,
            max_model_tokens=100_000,
            max_artifact_bytes=1_000_000,
        ),
        origin="https://issuer.example",
        policy_version="policies/host/policy@v1",
    )


TENANT_A = _host_context("tenant-a")
TENANT_B = _host_context("tenant-b")


def _adapter(tmp_path: Path) -> tuple[RouteAdapter, object]:
    stores = sqlite_control_plane_stores(tmp_path / "control.sqlite")
    app = create_app(
        str(tmp_path / "api.sqlite"),
        settings=_settings(),
        stores=stores,
    )
    return RouteAdapter(app), app


def _settings() -> object:
    from zebra_agent_config import load_settings

    return load_settings(env={"ZEBRA_PROFILE": "local"})


def _create_session(
    adapter: RouteAdapter,
    *,
    host_context: HostContextEnvelope | None,
) -> ApiResponse:
    return adapter.handle(
        RouteRequest(
            method="POST",
            path="/sessions",
            body={"prompt": "tenant isolation probe", "execute": False},
            host_context=host_context,
        )
    )


def _get(adapter: RouteAdapter, path: str, host_context: object) -> ApiResponse:
    return adapter.handle(
        RouteRequest(method="GET", path=path, host_context=host_context)
    )


def test_session_read_is_tenant_scoped(tmp_path: Path) -> None:
    adapter, _app = _adapter(tmp_path)
    created = _create_session(adapter, host_context=TENANT_A)
    assert created.status_code == 201
    session_id = created.body["session_id"]

    own = _get(adapter, f"/sessions/{session_id}", TENANT_A)
    assert own.status_code == 200
    other = _get(adapter, f"/sessions/{session_id}", TENANT_B)
    assert other.status_code == 404
    internal = _get(adapter, f"/sessions/{session_id}", None)
    assert internal.status_code == 200

    store = adapter.app.stores.sessions.get_session(adapter.app._parse_session_id(session_id))
    assert store is not None and store.namespace_id == "tenant-a"


def test_session_listing_is_tenant_scoped(tmp_path: Path) -> None:
    adapter, _app = _adapter(tmp_path)
    created_a = _create_session(adapter, host_context=TENANT_A)
    created_b = _create_session(adapter, host_context=TENANT_B)
    assert created_a.status_code == 201 and created_b.status_code == 201

    listed_a = _get(adapter, "/sessions", TENANT_A)
    listed_b = _get(adapter, "/sessions", TENANT_B)
    assert listed_a.status_code == 200 and listed_b.status_code == 200
    ids_a = {item["session_id"] for item in listed_a.body["sessions"]}
    ids_b = {item["session_id"] for item in listed_b.body["sessions"]}
    assert created_a.body["session_id"] in ids_a
    assert created_b.body["session_id"] not in ids_a
    assert created_b.body["session_id"] in ids_b
    assert created_a.body["session_id"] not in ids_b


def test_approval_routes_are_tenant_scoped(tmp_path: Path) -> None:
    adapter, _app = _adapter(tmp_path)
    created = _create_session(adapter, host_context=TENANT_A)
    session_id = created.body["session_id"]

    denied = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session_id}/approve",
            body={},
            host_context=TENANT_B,
        )
    )
    assert denied.status_code == 404
    listed = _get(adapter, "/approvals", TENANT_B)
    assert listed.status_code == 200
    assert all(
        entry.get("session_id") != session_id for entry in listed.body["approvals"]
    )


def test_task_routes_are_tenant_scoped(tmp_path: Path) -> None:
    adapter, _app = _adapter(tmp_path)
    created = _create_session(adapter, host_context=TENANT_A)
    session_id = created.body["session_id"]

    denied = _get(adapter, f"/tasks/{session_id}", TENANT_B)
    assert denied.status_code == 404
    allowed = _get(adapter, f"/tasks/{session_id}", TENANT_A)
    assert allowed.status_code == 200


def test_unnamespaced_sessions_stay_operator_scoped(tmp_path: Path) -> None:
    adapter, _app = _adapter(tmp_path)
    created = _create_session(adapter, host_context=None)
    session_id = created.body["session_id"]

    assert _get(adapter, f"/sessions/{session_id}", TENANT_B).status_code == 200
    assert _get(adapter, f"/sessions/{session_id}", TENANT_A).status_code == 200
    listed = _get(adapter, "/sessions", TENANT_B)
    assert any(
        item["session_id"] == session_id for item in listed.body["sessions"]
    )
