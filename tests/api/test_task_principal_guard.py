from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from zebra_agent_api.routes import RouteRequest
from zebra_agent_api.tenant_guard import tenant_scope_response

TASK_ID = "11111111-1111-1111-1111-111111111111"


def _context(principal: str) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id=f"grant-{principal}",
        host_app_id="trench",
        namespace_id="trench-prod",
        workspace_ref="workspace-1",
        resource_refs=(
            HostResourceRef(type="thread", id=TASK_ID),
            HostResourceRef(type="principal", id=principal),
        ),
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


def test_principal_bound_task_hides_artifacts_from_another_user(monkeypatch) -> None:
    owner = _context("user-a")
    binding = SimpleNamespace(
        host_capability=SimpleNamespace(host_context=owner),
    )
    monkeypatch.setattr(
        "zebra_agent_api.tenant_guard.load_task_binding",
        lambda *args, **kwargs: binding,
    )
    session = SimpleNamespace(namespace_id="trench-prod")
    app = SimpleNamespace(
        stores=SimpleNamespace(
            deployment_namespace="trench-prod",
            sessions=SimpleNamespace(get_session=lambda _: session),
        ),
        settings=SimpleNamespace(database_url="postgresql://unused"),
    )

    denied = tenant_scope_response(
        app,
        RouteRequest(
            method="GET",
            path=f"/tasks/{TASK_ID}/artifacts",
            host_context=_context("user-b"),
        ),
    )
    allowed = tenant_scope_response(
        app,
        RouteRequest(
            method="GET",
            path=f"/tasks/{TASK_ID}/artifacts",
            host_context=owner,
        ),
    )

    assert denied is not None and denied.status_code == 404
    assert allowed is None
