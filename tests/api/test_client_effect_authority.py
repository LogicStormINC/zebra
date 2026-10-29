"""A Session secret cannot widen fresh Host authority to another Task/Run."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agent_core.domain.client_capabilities import canonical_client_capability_digest
from agent_core.domain.client_effects import ClientEffectRequest
from zebra_agent_api.client_runtime_routes import handle_client_runtime_route

from tests.api.test_client_surface_open import opening


def effect_surface():
    app, bundle, request = opening()
    opened = handle_client_runtime_route(app, request)
    assert opened.status_code == 201
    now = datetime.now(UTC)
    published_action = next(
        action
        for profile in bundle.frontend_capabilities.profiles.values()
        for action in profile.actions
        if action.name == "app.ui.item.open"
    )
    effect = ClientEffectRequest(
        effect_id=uuid4(),
        task_id=UUID(request.path.split("/")[3]),
        parent_session_id=UUID(request.path.split("/")[3]),
        run_id="fixture-run",
        client_session_id=UUID(opened.body["client_session_id"]),
        tool_call_id=uuid4(),
        action_name="app.ui.item.open",
        arguments={"itemId": "private-item"},
        action_contract_digest=canonical_client_capability_digest(
            published_action.model_dump(mode="json")
        ),
        client_binding_digest=opened.body["binding_digest"],
        fence_hash="c" * 64,
        expected_ui_revision=1,
        idempotency_key=f"effect:{uuid4()}",
        requested_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    effects = {effect.effect_id: effect}
    accepted = []

    def accept(receipt, **kwargs):
        accepted.append(receipt)
        return SimpleNamespace(receipt=receipt, replayed=False, resume_command_id="resume-1")

    dispatch = SimpleNamespace(
        get_effect=lambda key: effects.get(key),
        list_pending=lambda session, limit: tuple(effects.values())[:limit],
    )
    bundle = replace(
        bundle,
        client_effects=dispatch,
        client_effect_receipts=SimpleNamespace(accept_receipt=accept),
    )
    app.client_platform = bundle
    request = replace(
        request,
        headers={
            "X-Zebra-Client-Session": opened.body["session_credential"],
            "X-Zebra-Client-Fence": opened.body["controller_fence_token"],
            "Idempotency-Key": "receipt-authority-check",
        },
    )
    return app, bundle, request, effect, effects, accepted


def effect_request(request, effect, operation):
    path = (
        f"/v1/client-sessions/{effect.client_session_id}/effects"
        if operation == "list"
        else f"/v1/client-effects/{effect.effect_id}"
    )
    body = None
    if operation == "receipt":
        path += "/receipts"
        body = {
            "receipt_id": str(uuid4()),
            "status": "succeeded",
            "result": {"opened": True},
            "received_at": datetime.now(UTC).isoformat(),
        }
    return replace(
        request, method="POST" if operation == "receipt" else "GET", path=path, body=body
    )


def alter_authority(request, fault):
    grant = request.verified_host_grant
    if fault == "issuer":
        grant = replace(grant, authority_issuer="https://foreign.test")
    elif fault == "scope":
        grant = replace(grant, context=grant.context.model_copy(update={"scopes": ("event.read",)}))
    elif fault == "expired":
        grant = replace(
            grant,
            context=grant.context.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            ),
        )
    else:
        kind = {"run": "run", "thread": "thread", "principal": "principal"}[fault]
        grant = replace(
            grant,
            context=grant.context.model_copy(
                update={
                    "resource_refs": tuple(
                        ref.model_copy(update={"resource_id": "foreign"})
                        if ref.resource_type == kind
                        else ref
                        for ref in grant.context.resource_refs
                    )
                }
            ),
        )
    return replace(request, host_context=grant.context, verified_host_grant=grant)


@pytest.mark.parametrize("operation", ["list", "detail", "receipt"])
@pytest.mark.parametrize("fault", ["run", "thread", "principal", "issuer", "scope", "expired"])
def test_effect_paths_require_current_resource_authority(operation, fault):
    app, _, request, effect, _, accepted = effect_surface()
    response = handle_client_runtime_route(
        app, alter_authority(effect_request(request, effect, operation), fault)
    )
    if operation == "list" and fault in {"run", "thread", "principal", "issuer"}:
        assert response.status_code == 200
        assert response.body == {"effects": []}
    else:
        assert response.status_code == (
            401 if fault == "expired" else 403 if fault == "scope" else 404
        )
    assert accepted == []
    assert "private-item" not in str(response.body)


@pytest.mark.parametrize("operation", ["list", "detail", "receipt"])
def test_correct_effect_resource_keeps_existing_contract(operation):
    app, _, request, effect, _, accepted = effect_surface()
    response = handle_client_runtime_route(app, effect_request(request, effect, operation))
    assert response.status_code == 200, response.body
    if operation == "list":
        assert response.body["effects"][0]["arguments"] == effect.arguments
    elif operation == "detail":
        assert response.body["request_digest"] == effect.request_digest
    else:
        assert len(accepted) == 1
        assert response.body["resume_command_id"] == "resume-1"


@pytest.mark.parametrize("operation", ["list", "detail", "receipt"])
def test_effect_authority_storage_failure_is_not_empty_or_success(operation):
    app, _, request, effect, _, accepted = effect_surface()

    def unavailable(_):
        raise OSError("binding store unavailable")

    app.cloud_control.load_task_binding = unavailable
    response = handle_client_runtime_route(app, effect_request(request, effect, operation))
    assert response.status_code == 503
    assert accepted == []


def test_pending_list_filters_mixed_resources_and_reuses_only_request_local_fact():
    app, _, request, effect, effects, _ = effect_surface()
    wrong = effect.model_copy(
        update={
            "effect_id": uuid4(),
            "run_id": "foreign",
            "arguments": {"private": "foreign-secret"},
        }
    )
    effects[wrong.effect_id] = wrong
    duplicate = effect.model_copy(update={"effect_id": uuid4()})
    effects[duplicate.effect_id] = duplicate
    original = app.cloud_control.load_task_binding
    reads = []

    def read(task):
        reads.append(task)
        return original(task)

    app.cloud_control.load_task_binding = read
    route = effect_request(request, effect, "list")
    response = handle_client_runtime_route(app, route)
    assert [row["effect_id"] for row in response.body["effects"]] == [
        str(effect.effect_id),
        str(duplicate.effect_id),
    ]
    assert "foreign-secret" not in str(response.body)
    assert len(reads) == 2
    app.cloud_control.load_task_binding = lambda _: None
    assert handle_client_runtime_route(app, route).body == {"effects": []}


@pytest.mark.parametrize("operation", ["list", "detail", "receipt"])
def test_other_task_is_hidden_even_with_same_session_and_run(operation):
    app, _, request, effect, effects, accepted = effect_surface()
    other = effect.model_copy(update={"task_id": uuid4()})
    effects[effect.effect_id] = other
    response = handle_client_runtime_route(app, effect_request(request, effect, operation))
    assert response.status_code == (200 if operation == "list" else 404)
    if operation == "list":
        assert response.body == {"effects": []}
    assert accepted == []


def test_empty_list_still_requires_scope():
    app, _, request, effect, effects, _ = effect_surface()
    effects.clear()
    response = handle_client_runtime_route(
        app, alter_authority(effect_request(request, effect, "list"), "scope")
    )
    assert response.status_code == 403


@pytest.mark.parametrize("operation", ["list", "detail", "receipt"])
def test_local_runtime_keeps_original_session_only_compatibility(operation):
    app, _, request, effect, _, accepted = effect_surface()
    app.settings = SimpleNamespace(deployment="local")
    route = alter_authority(effect_request(request, effect, operation), "run")
    assert handle_client_runtime_route(app, route).status_code == 200
    assert len(accepted) == (1 if operation == "receipt" else 0)
