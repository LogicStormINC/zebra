from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from zebra_agent_api.routes import RouteRequest
from zebra_agent_api.session_binding import _build_binding_snapshot
from zebra_agent_api.tenant_guard import task_access_response, tenant_scope_response

TASK_ID = "11111111-1111-1111-1111-111111111111"


def test_not_ready_principal_binding_is_not_misreported_as_missing() -> None:
    def load(_):
        raise CheckpointNotReady("binding frontier pending")

    app = SimpleNamespace(
        stores=SimpleNamespace(
            deployment_namespace="trench-prod",
            sessions=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(namespace_id="trench-prod")
            ),
        ),
        cloud_control=SimpleNamespace(deployment_namespace="trench-prod", load_task_binding=load),
    )
    response = task_access_response(app, TASK_ID, _context("user-a"))
    assert response is not None and response.status_code == 409
    assert response.body == {"status": "projection_not_ready", "retryable": True}


def _context(principal: str) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id=f"grant-{principal}",
        host_app_id="trench",
        namespace_id="trench-prod",
        workspace_ref="workspace-1",
        resource_refs=(
            HostResourceRef(type="thread", id="trench-bootstrap-principal-opaque"),
            HostResourceRef(type="run", id="principal-read-run"),
            HostResourceRef(type="principal", id=principal),
        ),
        scopes=("agent.run", "artifact.read"),
        limits=HostTechnicalLimits(
            max_runtime_seconds=60,
            max_model_tokens=1000,
            max_artifact_bytes=1024,
        ),
        origin="https://trench.local",
        policy_version="v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def _context_without_principal() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-missing-principal",
        host_app_id="trench",
        namespace_id="trench-prod",
        workspace_ref="workspace-1",
        resource_refs=(HostResourceRef(type="thread", id="trench-bootstrap-principal-opaque"),),
        scopes=("agent.run", "artifact.read"),
        limits=HostTechnicalLimits(
            max_runtime_seconds=60,
            max_model_tokens=1000,
            max_artifact_bytes=1024,
        ),
        origin="https://trench.local",
        policy_version="v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def _verified(context: HostContextEnvelope) -> VerifiedHostGrant:
    principal = next(
        ref.resource_id for ref in context.resource_refs if ref.resource_type == "principal"
    )
    return VerifiedHostGrant(
        context, context.grant_id, JwtAlgorithm.RS256, "https://broker.trench.local", principal
    )


def _binding(context: HostContextEnvelope):
    return _build_binding_snapshot(
        TASK_ID,
        host_context=context,
        verified_host_grant=_verified(context),
        definition_snapshot_digest="a" * 64,
    )


def test_principal_bound_task_hides_artifacts_from_another_user(monkeypatch) -> None:
    owner = _context("user-a")
    binding = _binding(owner)
    session = SimpleNamespace(namespace_id="trench-prod")
    app = SimpleNamespace(
        stores=SimpleNamespace(
            deployment_namespace="trench-prod",
            sessions=SimpleNamespace(get_session=lambda _: session),
        ),
        settings=SimpleNamespace(database_url="postgresql://unused"),
        cloud_control=SimpleNamespace(
            deployment_namespace="trench-prod", load_task_binding=lambda _: binding
        ),
    )

    other = _context("user-b")
    denied = tenant_scope_response(
        app,
        RouteRequest(
            method="GET",
            path=f"/tasks/{TASK_ID}/artifacts",
            host_context=other,
            verified_host_grant=_verified(other),
        ),
    )
    allowed = tenant_scope_response(
        app,
        RouteRequest(
            method="GET",
            path=f"/tasks/{TASK_ID}/artifacts",
            host_context=owner,
            verified_host_grant=_verified(owner),
        ),
    )

    assert denied is not None and denied.status_code == 404
    assert allowed is None


def test_agui_task_access_uses_the_same_principal_fence(monkeypatch) -> None:
    owner = _context("user-a")
    binding = _binding(owner)
    app = SimpleNamespace(
        stores=SimpleNamespace(
            deployment_namespace="trench-prod",
            sessions=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(namespace_id="trench-prod")
            ),
        ),
        settings=SimpleNamespace(database_url="postgresql://unused"),
        cloud_control=SimpleNamespace(
            deployment_namespace="trench-prod", load_task_binding=lambda _: binding
        ),
    )

    denied = task_access_response(app, TASK_ID, _context("user-b"))
    allowed = task_access_response(app, TASK_ID, owner)

    assert denied is not None and denied.status_code == 404
    assert allowed is None


def test_host_task_access_fails_closed_without_a_principal() -> None:
    app = SimpleNamespace(
        stores=SimpleNamespace(
            deployment_namespace="trench-prod",
            sessions=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(namespace_id="trench-prod")
            ),
        ),
        settings=SimpleNamespace(database_url="postgresql://unused"),
    )

    denied = task_access_response(app, TASK_ID, _context_without_principal())

    assert denied is not None and denied.status_code == 404
