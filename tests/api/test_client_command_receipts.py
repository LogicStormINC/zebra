"""The receipt is an authorized persisted admission observation, never command replay."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.client_sessions import ClientSessionStatus
from agent_storage import SQLiteEventStore
from zebra_agent_api.routes import RouteRequest

from tests.api.test_agui_bound_client_state import setup_surface


def fixture(tmp_path):
    adapter, platform, headers, body, db, task = setup_surface(tmp_path)
    response = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert response.status_code == 202
    headers = {**headers, "X-Zebra-Command-Segment": str(task)}
    path = f"/agui/threads/{task}/runs/run-1/command-receipt"
    return adapter, platform, headers, path, db, task, response.body["command_id"]


def test_lost_response_receipt_reopens_durable_command_without_writing(tmp_path):
    adapter, _, headers, path, db, task, command_id = fixture(tmp_path)
    before = SQLiteEventStore(db).list_for_session(task)
    for _ in range(2):
        observed = adapter.handle(RouteRequest("GET", path, headers=headers))
        assert observed.status_code == 200
        assert observed.body == {"status": "accepted", "commandId": command_id}
    assert SQLiteEventStore(db).list_for_session(task) == before
    assert "never-persist" not in repr(observed.body)


@pytest.mark.parametrize(
    "change",
    [
        {"Idempotency-Key": "missing"},
        {"Idempotency-Key": "different"},
    ],
)
def test_missing_is_only_not_observed_and_never_resend_permission(tmp_path, change):
    adapter, _, headers, path, _, _, _ = fixture(tmp_path)
    response = adapter.handle(RouteRequest("GET", path, headers={**headers, **change}))
    assert response.status_code == 200
    assert response.body == {"status": "not_observed"}


@pytest.mark.parametrize(
    "change,code",
    [
        ({"X-Zebra-Client-Session": "bad"}, 401),
        ({"X-Zebra-Command-Segment": str(uuid4())}, 404),
        ({"X-Zebra-Command-Segment": "invalid"}, 400),
        ({"Idempotency-Key": ""}, 400),
        ({"Idempotency-Key": "x" * 257}, 400),
        ({"Idempotency-Key": "line\nbreak"}, 400),
    ],
)
def test_credentials_original_segment_and_key_required(tmp_path, change, code):
    adapter, _, headers, path, _, _, _ = fixture(tmp_path)
    response = adapter.handle(RouteRequest("GET", path, headers={**headers, **change}))
    assert response.status_code == code


def test_wrong_run_no_body_query_and_closed_session_rejected(tmp_path):
    adapter, platform, headers, path, _, _, _ = fixture(tmp_path)
    assert adapter.handle(
        RouteRequest("GET", path.replace("run-1", "run-2"), headers=headers)
    ).body == {"status": "not_observed"}
    for request in [
        RouteRequest("GET", path, headers=headers, body={"x": 1}),
        RouteRequest("GET", path, headers=headers, query={"key": "x"}),
    ]:
        assert adapter.handle(request).status_code == 400
    sid = headers["X-Zebra-Client-Session"].split(":")[0]
    platform.client_sessions.sessions[sid] = platform.client_sessions.sessions[sid].model_copy(
        update={"status": ClientSessionStatus.CLOSED}
    )
    assert adapter.handle(RouteRequest("GET", path, headers=headers)).status_code == 401


def test_dependency_error_and_missing_port_fail_closed(tmp_path):
    adapter, _, headers, path, _, _, _ = fixture(tmp_path)
    from zebra_agent_api.ag_ui_command_receipts import handle_client_command_receipt

    shadow = SimpleNamespace(
        stores=SimpleNamespace(events=object()), client_platform=adapter.app.client_platform
    )
    assert (
        handle_client_command_receipt(
            shadow, RouteRequest("GET", path, headers=headers)
        ).status_code
        == 503
    )


def test_current_task_authorization_rechecked_after_read(tmp_path, monkeypatch):
    import zebra_agent_api.ag_ui_command_receipts as receipts
    from zebra_agent_api.responses import ApiResponse

    adapter, _, headers, path, _, _, _ = fixture(tmp_path)
    guard = Mock(side_effect=[None, ApiResponse(403, {"status": "revoked"})])
    monkeypatch.setattr(receipts, "task_access_response", guard)
    assert adapter.handle(RouteRequest("GET", path, headers=headers)).status_code == 403
    assert guard.call_count == 2
    assert guard.call_args.kwargs["required_scope"] == "agent.run"
    assert guard.call_args.kwargs["run_id"] == "run-1"


def test_cloud_requires_independently_verified_current_host_subject(tmp_path):
    adapter, _, headers, path, _, _, _ = fixture(tmp_path)
    from zebra_agent_api.ag_ui_command_receipts import handle_client_command_receipt

    shadow = SimpleNamespace(
        stores=adapter.app.stores,
        client_platform=adapter.app.client_platform,
        settings=SimpleNamespace(deployment="cloud"),
    )
    assert (
        handle_client_command_receipt(
            shadow, RouteRequest("GET", path, headers=headers)
        ).status_code
        == 401
    )


def test_asgi_route_headers_query_and_no_get_body(tmp_path, monkeypatch):
    import zebra_agent_api.http as http
    from fastapi.testclient import TestClient

    adapter, _, headers, path, _, _, cid = fixture(tmp_path)
    monkeypatch.setattr(http, "create_app", lambda *args, **kwargs: adapter.app)
    with TestClient(http.create_http_app(settings=adapter.app.settings)) as client:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "accepted", "commandId": cid}
        assert client.request("GET", path, headers=headers, content="{}").status_code == 400
        assert client.get(path + "?key=bad", headers=headers).status_code == 400


def test_session_revocation_during_receipt_read_is_not_disclosed(tmp_path, monkeypatch):
    adapter, platform, headers, path, _, _, _ = fixture(tmp_path)
    original = adapter.app.stores.events.read_client_command_receipt
    sid = headers["X-Zebra-Client-Session"].split(":")[0]

    def revoke(*args):
        result = original(*args)
        platform.client_sessions.sessions[sid] = platform.client_sessions.sessions[sid].model_copy(
            update={"status": ClientSessionStatus.CLOSED}
        )
        return result

    monkeypatch.setattr(adapter.app.stores.events, "read_client_command_receipt", revoke)
    assert adapter.handle(RouteRequest("GET", path, headers=headers)).status_code == 401


def test_reader_dependency_failure_never_becomes_not_observed(tmp_path, monkeypatch):
    adapter, _, headers, path, _, _, _ = fixture(tmp_path)

    def failed(*args):
        raise OSError("private backend detail")

    monkeypatch.setattr(adapter.app.stores.events, "read_client_command_receipt", failed)
    response = adapter.handle(RouteRequest("GET", path, headers=headers))
    assert response.status_code == 503
    assert "private" not in repr(response.body)


def test_database_budget_covers_authorization_and_receipt_read(tmp_path, monkeypatch):
    from time import monotonic

    from agent_storage.postgres.task_io import current_task_io_deadline

    adapter, _, headers, path, _, _, _ = fixture(tmp_path)
    original = adapter.app.stores.events.read_client_command_receipt

    def bounded(*args):
        deadline = current_task_io_deadline()
        assert deadline is not None and 0 < deadline - monotonic() <= 2
        return original(*args)

    monkeypatch.setattr(adapter.app.stores.events, "read_client_command_receipt", bounded)
    assert adapter.handle(RouteRequest("GET", path, headers=headers)).status_code == 200
    assert current_task_io_deadline() is None
