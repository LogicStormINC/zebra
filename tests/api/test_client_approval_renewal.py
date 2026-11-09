"""Approval renewal wiring: authorization first, GET-only recovery stays read-only."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from zebra_agent_api import client_approval_operations as api
from zebra_agent_api import session_binding
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteRequest

from tests.api.test_client_approval_operations import fixture


def decision():
    return {"decision": "approve", "expected_revision": 0, "operator": "user", "reason": "explicit"}


def test_unauthorized_controller_cannot_renew_before_rejection(tmp_path, monkeypatch):
    adapter, _, headers, path, port = fixture(tmp_path)
    renewals = []
    monkeypatch.setattr(
        session_binding, "renew_host_binding_for_command", lambda *a: renewals.append(a)
    )
    response = adapter.handle(RouteRequest("POST", path, headers=headers, body=decision()))
    assert response.status_code in {401, 403, 409}
    assert renewals == []
    assert port.reads == 0


def test_original_get_never_renews_binding(tmp_path, monkeypatch):
    adapter, _, headers, path, port = fixture(tmp_path)

    def forbidden(*_):
        raise AssertionError("GET receipt must never refresh authority")

    monkeypatch.setattr(session_binding, "renew_host_binding_for_command", forbidden)
    response = adapter.handle(RouteRequest("GET", path, headers=headers))
    assert response.status_code == 200
    assert port.reads == 1


@pytest.mark.parametrize("status", [403, 409, 503])
def test_authorized_post_renews_before_lock_and_failure_prevents_approval(
    tmp_path, monkeypatch, status
):
    adapter, _, headers, path, port = fixture(tmp_path)
    order = []
    grant = object()  # Wiring sentinel only; signed grant validation belongs to the reused helper.

    def current(*_):
        order.append("authorize")
        return SimpleNamespace(client_session_id=uuid4())

    def renew(app, task, verified):
        assert app is adapter.app
        assert task == path.split("/")[3]
        assert verified is grant
        order.append("renew")
        return ApiResponse(status, {"status": "host_binding_renewal_rejected"})

    monkeypatch.setattr(api, "_current", current)
    monkeypatch.setattr(session_binding, "renew_host_binding_for_command", renew)
    request = RouteRequest(
        "POST", path, headers=headers, body=decision(), verified_host_grant=grant
    )
    response = api.handle_client_approval_operation(adapter.app, request)
    assert response.status_code == status
    assert order == ["authorize", "renew"]
    assert port.reads == 0
