"""Real native MESSAGE/Worker input and observation-only official POST composition."""

from dataclasses import replace
from datetime import timedelta

from agent_core.domain.client_sessions import ClientControlFence
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
from fastapi.testclient import TestClient
from zebra_agent_api.http import create_http_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_worker.command_consumer import SessionCommandConsumer

from tests.agent_integrations.binding_store_cases import resolve
from tests.api.test_agui_bound_client_state import setup_surface
from tests.api.test_agui_public_slice import PROFILE
from tests.worker.execution.worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
)


def prepared_surface(tmp_path):
    adapter, platform, headers, body, database, task = setup_surface(tmp_path)
    app = replace(adapter.app, agui_profiles=AgUiProfileRegistry((PROFILE,)))
    adapter = RouteAdapter(app)
    fence = ClientControlFence.issue()
    binding = next(iter(platform.client_sessions.bindings.values()))
    platform.client_control_leases.claim_controller(
        binding.binding_id,
        task_id=task,
        run_id="run-1",
        client_session_id=binding.client_session_id,
        fence=fence,
        ttl=timedelta(minutes=5),
    )
    headers.update(
        {
            "X-Zebra-Client-Fence": fence.token,
            "X-Zebra-Command-Segment": str(task),
            "X-Zebra-AGUI-Profile": PROFILE.profile_id,
        }
    )
    value = {
        "threadId": str(task),
        "runId": "run-1",
        "messages": [
            {"id": "new-user", "role": "user", "content": "ACTUAL NEW MESSAGE TO THE MODEL"}
        ],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": body["input"]["forwardedProps"],
    }
    return (
        adapter,
        headers,
        {"expectedRevision": body["expectedRevision"], "input": value},
        database,
        task,
    )


def materialize(app, task):
    stores = app.stores
    for method in (
        stores.tasks.backfill_event_positions,
        stores.tasks.backfill_replay_headers,
        stores.tasks.backfill_projection_sources,
    ):
        while not method(TaskId(task), limit=256):
            pass
    run = stores.tasks.read_run_header(TaskId(task), "run-1")
    scope = ProjectionScope(
        "local", TaskId(task), run.anchor.event_id, PROFILE.checkpoint_version()
    )
    resolve(stores.tasks, run, scope)
    identity = AgUiRunIdentity(session_id=task, thread_id=str(task), run_id="run-1")
    after = stores.tasks.read_checkpoint_head(scope).through_sequence
    while after < run.highwater:
        page = stores.tasks.read_event_page(
            TaskId(task), after, limit=256, through_sequence=run.highwater
        )
        plan = build_projection_page_plan(stores.tasks, page, run, scope, identity, profile=PROFILE)
        result = AgUiCheckpointMaterializer(stores.tasks, profile=PROFILE).prepare_page(
            page, plan, scope, identity
        )
        stores.tasks.commit_projection_page(result)
        after = page.next_sequence


def test_native_message_reaches_actual_worker_fake_provider_and_standard_post_is_read_only(
    tmp_path, monkeypatch
):
    from agent_core.application import SessionBootstrapService
    from agent_core.domain.turns import InteractionMode

    build = SessionBootstrapService.build
    monkeypatch.setattr(
        SessionBootstrapService,
        "build",
        lambda self, command: build(
            self, replace(command, interaction_mode=InteractionMode.CONVERSATION)
        ),
    )
    adapter, headers, body, database, task = prepared_surface(tmp_path)
    body["input"]["state"] = {"app.ui.route": {"truth": True, "nested": [False, {"count": 1.0}]}}
    initial_gateway = _assistant_only_gateway(settings=adapter.app.settings)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway", lambda settings: initial_gateway
    )
    _build_execution_service(database).execute_session(task, worker_id="agui-initial-fixture")
    body["expectedRevision"] = adapter.app.stores.sessions.get_session(task).current_sequence
    base = f"/agui/threads/{task}/runs/run-1"
    response = adapter.handle(RouteRequest("POST", base + "/prepare", headers=headers, body=body))
    assert response.status_code == 202, response.body
    commands = [
        event
        for event in adapter.app.stores.events.list_for_session(task)
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED
    ]
    assert len(commands) == 1 and commands[0].payload["kind"] == "message"
    gateway = _assistant_only_gateway(settings=adapter.app.settings)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway", lambda settings: gateway
    )
    consumer = SessionCommandConsumer(adapter.app.stores, _build_execution_service(database))
    result = consumer.consume_once(worker_id="agui-native-test", lease_ttl_seconds=30)
    assert result.status == "executed", result
    assert "ACTUAL NEW MESSAGE TO THE MODEL" in repr(gateway.requests)
    assert (
        consumer.consume_once(worker_id="agui-native-test", lease_ttl_seconds=30).status == "idle"
    )
    materialize(adapter.app, task)
    prepared = adapter.handle(RouteRequest("GET", base + "/prepared", headers=headers))
    assert prepared.status_code == 200 and prepared.body["status"] == "prepared", prepared.body
    actual_input = prepared.body["input"]
    assert actual_input["runId"].startswith("agui:")
    before = adapter.app.stores.events.list_for_session(task)
    # The client no longer controls this Surface; observation still needs only read authority.
    adapter.app.client_platform.client_control_leases._lease = None
    monkeypatch.setattr("zebra_agent_api.http.create_app", lambda *a, **k: adapter.app)
    client = TestClient(
        create_http_app(database, settings=adapter.app.settings, stores=adapter.app.stores)
    )
    response = client.post(base + "/stream", headers=headers, json=actual_input)
    assert response.status_code == 200, response.text
    assert '"type":"RUN_STARTED"' in response.text
    assert '"type":"RUN_FINISHED"' in response.text
    assert "Worker completed the session." in response.text
    assert "zebra.stream." not in response.text
    assert adapter.app.stores.events.list_for_session(task) == before
    wrong = {
        **actual_input,
        "messages": [{"id": "spoof", "role": "user", "content": "not admitted"}],
    }
    assert client.post(base + "/stream", headers=headers, json=wrong).status_code == 409
    assert adapter.app.stores.events.list_for_session(task) == before

    from copy import deepcopy

    for field in ("truth", "nested"):
        candidate = deepcopy(actual_input)
        route = candidate["state"]["app.ui.route"]
        if field == "truth":
            route["truth"] = 1
        else:
            route["nested"][0] = 0
        assert client.post(base + "/stream", headers=headers, json=candidate).status_code == 409
    reordered = dict(reversed(list(actual_input.items())))
    assert client.post(base + "/stream", headers=headers, json=reordered).status_code == 200
    assert adapter.app.stores.events.list_for_session(task) == before

    numeric = deepcopy(actual_input)
    numeric["state"]["app.ui.route"]["nested"][1]["count"] = 1
    assert client.post(base + "/stream", headers=headers, json=numeric).status_code == 200
    assert adapter.app.stores.events.list_for_session(task) == before


def test_native_prepare_revision_cannot_silently_fall_back_to_revision_one(tmp_path):
    adapter, headers, body, _database, task = prepared_surface(tmp_path)
    before = adapter.app.stores.events.list_for_session(task)
    for revision in ("2", "02", " 1", "0", "bad"):
        response = adapter.handle(
            RouteRequest(
                "POST",
                f"/agui/threads/{task}/runs/run-1/prepare",
                headers={**headers, "X-Zebra-AGUI-Revision": revision},
                body=body,
            )
        )
        assert response.status_code == 409, response.body
        assert response.body["status"] == "agui_preparation_conflict"
        assert adapter.app.stores.events.list_for_session(task) == before
