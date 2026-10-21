"""Durable Effect and Task binding stores exercise the new transport guard."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from agent_core.domain.client_sessions import ClientControlFence
from agent_storage.postgres.client_effects import (
    PostgresClientEffectDispatch,
    PostgresClientEffectReceipts,
)
from agent_storage.postgres.client_sessions import (
    PostgresClientControlLeaseStore,
    PostgresClientSessionRegistry,
)
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres.task_admission import save_task_binding
from zebra_agent_api.client_runtime_routes import handle_client_runtime_route

from tests.agent_storage.test_postgres_client_effects import _continuation
from tests.agent_storage.test_postgres_client_effects import pytestmark as _postgres_mark
from tests.agent_storage.test_postgres_client_effects import stores as _stores
from tests.api.test_client_effect_authority import (
    alter_authority,
    effect_request,
    effect_surface,
)

stores = _stores
pytestmark = _postgres_mark


@pytest.fixture
def durable_surface(stores):
    dispatch, receipts, sessions, events, dsn, namespace = stores
    app, bundle, route, effect, _, _ = effect_surface()
    session = bundle.client_sessions.sessions[str(effect.client_session_id)]
    sessions.create_session(session.model_copy(update={"ui_revision": effect.expected_ui_revision}))
    binding = bundle.client_sessions.get_run_binding(
        effect.task_id, effect.run_id, effect.client_session_id
    )
    sessions.save_run_binding(binding)
    fence = ClientControlFence(token=route.headers["X-Zebra-Client-Fence"])
    PostgresClientControlLeaseStore(dsn, deployment_namespace=namespace).claim_controller(
        binding.binding_id,
        task_id=effect.task_id,
        run_id=effect.run_id,
        client_session_id=effect.client_session_id,
        fence=fence,
        ttl=timedelta(minutes=5),
    )
    effect = effect.model_copy(update={"fence_hash": fence.fence_hash})
    dispatch.schedule(
        effect, continuation=_continuation(effect), session_id=effect.parent_session_id
    )
    frozen = app.cloud_control.load_task_binding(effect.task_id)
    save_task_binding(
        dsn, deployment_namespace=namespace, binding=frozen, expected_previous_revision=0
    )
    app.stores.deployment_namespace = namespace
    app.cloud_control = PostgresDirectControl(dsn, deployment_namespace=namespace)
    app.client_platform = replace(
        bundle,
        deployment_namespace=namespace,
        client_sessions=sessions,
        client_effects=dispatch,
        client_effect_receipts=receipts,
    )
    return app, route, effect, events, dsn, namespace


def rows(events, effect):
    return events.list_for_session(effect.parent_session_id)


@pytest.mark.parametrize("operation", ["list", "detail", "receipt"])
def test_real_stores_deny_foreign_run_without_events_or_terminal_change(durable_surface, operation):
    app, route, effect, events, _, _ = durable_surface
    before = rows(events, effect)
    response = handle_client_runtime_route(
        app, alter_authority(effect_request(route, effect, operation), "run")
    )
    assert response.status_code == (200 if operation == "list" else 404)
    if operation == "list":
        assert response.body == {"effects": []}
    assert rows(events, effect) == before
    assert app.client_platform.client_effects.get_effect(effect.effect_id).status.value == "pending"


def test_lost_receipt_response_restart_and_replay_recheck_current_grant(durable_surface):
    app, route, effect, events, dsn, namespace = durable_surface
    request = effect_request(route, effect, "receipt")
    first = handle_client_runtime_route(app, request)
    assert first.status_code == 200, first.body
    assert first.body["replayed"] is False
    before = rows(events, effect)
    # New adapters represent a replacement process; all receipts and bindings are durable.
    app.cloud_control = PostgresDirectControl(dsn, deployment_namespace=namespace)
    app.client_platform = replace(
        app.client_platform,
        client_sessions=PostgresClientSessionRegistry(dsn, deployment_namespace=namespace),
        client_effects=PostgresClientEffectDispatch(dsn, deployment_namespace=namespace),
        client_effect_receipts=PostgresClientEffectReceipts(dsn, deployment_namespace=namespace),
    )
    denied = handle_client_runtime_route(app, alter_authority(request, "thread"))
    assert denied.status_code == 404
    replay = handle_client_runtime_route(
        app, replace(request, body={**request.body, "receipt_id": str(uuid4())})
    )
    assert replay.status_code == 200 and replay.body["replayed"] is True
    assert replay.body["resume_command_id"] == first.body["resume_command_id"]
    assert rows(events, effect) == before
    kinds = [event.event_type.value for event in before]
    assert (
        kinds.count("client_effect_receipt_accepted")
        == kinds.count("session_command_accepted")
        == 1
    )


def test_independent_receipt_adapters_converge_on_one_acceptance(durable_surface):
    app, route, effect, events, dsn, namespace = durable_surface
    request = effect_request(route, effect, "receipt")
    other = replace(
        app.client_platform,
        client_effect_receipts=PostgresClientEffectReceipts(dsn, deployment_namespace=namespace),
    )
    # Each entry uses independent Postgres connections; no in-process receipt lock.
    from types import SimpleNamespace

    second = SimpleNamespace(**vars(app))
    second.client_platform = other
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda target: handle_client_runtime_route(target, request), (app, second))
        )
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.body["replayed"] for response in responses) == [False, True]
    assert len({response.body["resume_command_id"] for response in responses}) == 1
    kinds = [event.event_type.value for event in rows(events, effect)]
    assert (
        kinds.count("client_effect_receipt_accepted")
        == kinds.count("session_command_accepted")
        == 1
    )


def test_current_resource_guard_keeps_fence_and_payload_conflicts(durable_surface):
    app, route, effect, events, _, _ = durable_surface
    request = effect_request(route, effect, "receipt")
    wrong = replace(
        request,
        headers={
            **request.headers,
            "X-Zebra-Client-Fence": "wrong-fence-value-at-least-thirty-two-characters",
        },
    )
    before = rows(events, effect)
    assert handle_client_runtime_route(app, wrong).status_code == 409
    assert rows(events, effect) == before
    assert handle_client_runtime_route(app, request).status_code == 200
    conflict = replace(request, body={**request.body, "result": {"opened": False}})
    assert handle_client_runtime_route(app, conflict).status_code == 409
    assert len(rows(events, effect)) == len(before) + 2
