"""Both opening and existing credential paths bind to the verified current subject."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from zebra_agent_api.client_runtime_routes import handle_client_runtime_route
from zebra_agent_api.routes import RouteRequest

from tests.api.test_client_surface_open import opening


@pytest.mark.parametrize("fault", ["subject", "context", "missing", "expired"])
def test_open_cannot_delegate_to_a_different_or_unverified_subject(fault):
    app, bundle, request = opening()
    if fault == "subject":
        request.body["grant"]["user_ref"] = "other-user"
    elif fault == "missing":
        request = replace(request, verified_host_grant=None)
    else:
        context = request.host_context.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            if fault == "expired"
            else {"workspace_ref": "foreign"}
        )
        verified = request.verified_host_grant
        if fault == "expired":
            verified = replace(verified, context=context)
        request = replace(request, host_context=context, verified_host_grant=verified)
    response = handle_client_runtime_route(app, request)
    assert response.status_code in {401, 403, 404}
    assert not bundle.client_sessions.sessions


def test_session_secret_cannot_cross_subject_and_original_bind_checks_thread_run():
    app, _, request = opening()
    opened = handle_client_runtime_route(app, request)
    assert opened.status_code == 201
    headers = {"X-Zebra-Client-Session": opened.body["session_credential"]}
    beat = RouteRequest(
        "POST",
        f"/v1/client-sessions/{opened.body['client_session_id']}/heartbeat",
        headers=headers,
        host_context=request.host_context,
        verified_host_grant=request.verified_host_grant,
    )
    assert handle_client_runtime_route(app, beat).status_code == 200
    assert (
        handle_client_runtime_route(
            app,
            replace(
                beat,
                verified_host_grant=replace(request.verified_host_grant, subject_ref="other-user"),
            ),
        ).status_code
        == 401
    )
    bind = replace(
        request,
        headers=headers,
        path=request.path.replace("client-surface", "client-bindings"),
        body={"task_capability_scope": ["app.ui.item.open"], "controller": True},
    )
    assert handle_client_runtime_route(app, bind).status_code == 201
    assert (
        handle_client_runtime_route(
            app, replace(bind, path=bind.path.replace("fixture-run", "foreign"))
        ).status_code
        == 404
    )


def test_original_binding_cannot_reacquire_controller_after_profile_revocation():
    from agent_core.domain.client_capabilities import ProfileLifecycle

    app, bundle, request = opening()
    opened = handle_client_runtime_route(app, request)
    assert opened.status_code == 201
    profile = next(iter(bundle.frontend_capabilities.profiles.values()))
    bundle.frontend_capabilities.set_lifecycle(
        profile.frontend_app_id, profile.revision, ProfileLifecycle.REVOKED
    )
    request = replace(
        request,
        path=request.path.replace("client-surface", "client-bindings"),
        headers={"X-Zebra-Client-Session": opened.body["session_credential"]},
        body={"controller": True, "task_capability_scope": ["app.ui.item.open"]},
    )
    assert handle_client_runtime_route(app, request).status_code == 409
