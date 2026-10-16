"""Compound opening keeps fresh Host target checks ahead of every mutation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_core.domain.client_capabilities import ProfileLifecycle
from zebra_agent_api.client_runtime_routes import handle_client_runtime_route
from zebra_agent_api.routes import RouteRequest

from tests.api.test_client_surface import surface
from tests.api.test_task_resource_binding import TASK, app_for, binding_for, verified
from tests.host_grant_broker.test_grant_broker import _key, _settings


def opening():
    _, bundle, session_id, _, body, _ = surface()
    key = _key()
    grant = verified((key, _settings(key)), run="fixture-run")
    client_grant = bundle.client_sessions.sessions.pop(session_id).grant.model_copy(
        update={
            "host_app_id": grant.context.host_app_id,
            "namespace_id": grant.context.namespace_id,
            "origin": grant.context.origin,
        }
    )
    bundle.frontend_capabilities.bindings["host"] = SimpleNamespace(
        host_app_id=grant.context.host_app_id,
        namespace_id=grant.context.namespace_id,
        frontend_app_id=client_grant.frontend_app_id,
        profile_digest=client_grant.profile_digest,
    )
    app = app_for(binding_for(grant))
    app.settings = SimpleNamespace(deployment="cloud")
    app.client_platform = bundle
    app.stores.tasks = SimpleNamespace(get_task=lambda _: SimpleNamespace(active_segment_id=TASK))
    body["mount"].pop("client_session_id")
    body["grant"] = client_grant.model_dump(mode="json")
    request = RouteRequest(
        "POST",
        f"/v1/tasks/{TASK}/runs/fixture-run/client-surface",
        body=body,
        host_context=grant.context,
        verified_host_grant=grant,
    )
    return app, bundle, request


def test_open_mount_bind_one_request_uses_existing_authority_and_credential():
    app, bundle, request = opening()
    response = handle_client_runtime_route(app, request)
    assert response.status_code == 201, response.body
    result = response.body
    assert result["session_credential"].startswith(result["client_session_id"] + ":")
    assert result["allowed_actions"] == ["app.ui.item.open"]
    assert len(bundle.client_sessions.sessions) == len(bundle.client_sessions.bindings) == 1
    # Original authenticated mount+bind remains available to callers holding the new credential.
    mount = {**request.body["mount"], "client_session_id": result["client_session_id"]}
    retry = handle_client_runtime_route(
        app,
        replace(
            request,
            headers={"X-Zebra-Client-Session": result["session_credential"]},
            body={k: v for k, v in {**request.body, "mount": mount}.items() if k != "grant"},
        ),
    )
    assert retry.status_code == 201
    assert retry.body["binding_id"] == result["binding_id"]
    assert retry.body["controller_fence_token"] != result["controller_fence_token"]


@pytest.mark.parametrize(
    "mismatch",
    [
        "unverified",
        "thread",
        "run",
        "issuer",
        "expired",
        "missing",
        "grant_host",
        "profile_revoked",
        "malformed",
        "session_id",
    ],
)
def test_rejects_before_session_creation(mismatch):
    app, bundle, request = opening()
    grant = request.verified_host_grant
    if mismatch == "unverified":
        request = replace(request, verified_host_grant=None)
    elif mismatch in {"thread", "run", "issuer", "expired", "missing"}:
        if mismatch == "thread":
            context = grant.context.model_copy(
                update={
                    "resource_refs": tuple(
                        ref.model_copy(update={"resource_id": "foreign"})
                        if ref.resource_type == "thread"
                        else ref
                        for ref in grant.context.resource_refs
                    )
                }
            )
            grant = replace(grant, context=context)
        if mismatch == "run":
            request = replace(request, path=request.path.replace("fixture-run", "foreign"))
        if mismatch == "issuer":
            grant = replace(grant, authority_issuer="https://foreign.test")
        if mismatch == "expired":
            grant = replace(
                grant,
                context=grant.context.model_copy(
                    update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                ),
            )
        request = replace(
            request,
            host_context=None if mismatch == "missing" else grant.context,
            verified_host_grant=grant,
        )
    elif mismatch == "grant_host":
        request.body["grant"]["host_app_id"] = "foreign"
    elif mismatch == "profile_revoked":
        profile = next(iter(bundle.frontend_capabilities.profiles.values()))
        bundle.frontend_capabilities.set_lifecycle(
            profile.frontend_app_id, 1, ProfileLifecycle.REVOKED
        )
    elif mismatch == "malformed":
        request.body["unknown"] = True
    else:
        request.body["mount"]["client_session_id"] = str(uuid4())
    response = handle_client_runtime_route(app, request)
    assert response.status_code in {400, 401, 403, 404, 409}, response.body
    assert bundle.client_sessions.sessions == bundle.client_sessions.snapshots == {}
    assert bundle.client_sessions.bindings == {}


def test_profile_is_rechecked_after_open_and_partial_failure_leaks_no_credential(monkeypatch):
    from zebra_agent_api import client_surface

    app, bundle, request = opening()
    original = client_surface.open_client_session

    def revoke_after_open(*args):
        response = original(*args)
        profile = next(iter(bundle.frontend_capabilities.profiles.values()))
        bundle.frontend_capabilities.set_lifecycle(
            profile.frontend_app_id, 1, ProfileLifecycle.REVOKED
        )
        return response

    monkeypatch.setattr(client_surface, "open_client_session", revoke_after_open)
    response = handle_client_runtime_route(app, request)
    assert response.status_code == 409
    assert "session_credential" not in response.body
    assert len(bundle.client_sessions.sessions) == 1
    assert bundle.client_sessions.snapshots == bundle.client_sessions.bindings == {}


def test_open_capability_is_cloud_only_and_requires_complete_stores():
    api, _, _, _, _, _ = surface()
    assert api.get_runtime_capabilities().body["client_surface_open_contract_version"] == 0
    cloud = replace(api, settings=replace(api.settings, profile="cloud"))
    assert cloud.get_runtime_capabilities().body["client_surface_open_contract_version"] == 1
    disabled = replace(cloud, client_platform=None)
    assert disabled.get_runtime_capabilities().body["client_surface_open_contract_version"] == 0
