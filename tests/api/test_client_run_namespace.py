"""Cloud Run binding compares the signed Host tenant, not the DB namespace."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from zebra_agent_api.client_grant_auth import ClientAuthContext
from zebra_agent_api.client_runtime_routes import handle_client_runtime_route
from zebra_agent_api.client_sessions import bind_client_run

from tests.api.test_client_surface_open import opening
from tests.api.test_task_resource_binding import TASK


@pytest.mark.parametrize(
    ("session_namespace", "expected_status"),
    [("trench-prod", 201), ("other-tenant", 404), (None, 403)],
)
def test_cloud_binding_uses_session_tenant(session_namespace, expected_status):
    app, bundle, request = opening()
    opened = handle_client_runtime_route(app, request)
    assert opened.status_code == 201
    assert app.stores.deployment_namespace != request.host_context.namespace_id
    app.stores.sessions.get_session = lambda _: (
        SimpleNamespace(namespace_id=session_namespace) if session_namespace is not None else None
    )
    original = bundle.client_control_leases._lease.fence_hash
    response = bind_client_run(
        app,
        TASK,
        "fixture-run",
        {"controller": False},
        ClientAuthContext(client_session_id=UUID(opened.body["client_session_id"])),
        request.host_context,
        request.verified_host_grant,
    )
    assert response.status_code == expected_status
    assert len(bundle.client_sessions.bindings) == 1
    assert bundle.client_control_leases._lease.fence_hash == original
