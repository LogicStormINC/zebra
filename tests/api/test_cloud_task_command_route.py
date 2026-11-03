from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteRequest
from zebra_agent_api.task_api import TaskReadApi
from zebra_agent_api.task_routes import handle_task_route


@pytest.mark.parametrize("action", ["resume", "suspend"])
def test_cloud_task_control_submits_on_active_segment(monkeypatch, action):
    app = Mock(settings=SimpleNamespace(deployment="cloud"))
    app.submit_command.return_value = ApiResponse(202, {"status": "queued"})
    active = Mock(return_value="active-segment")
    monkeypatch.setattr(TaskReadApi, "active_segment", active)

    def request(body):
        return RouteRequest(
            method="POST",
            path=f"/tasks/task-id/{action}",
            body=body,
            headers={"Idempotency-Key": "original-intent"},
        )

    assert handle_task_route(app, request({})).status_code == 400
    app.submit_command.assert_not_called()
    response = handle_task_route(app, request({"expected_revision": 3}))
    assert response.status_code == 202
    assert response.body["task_id"] == "task-id"
    active.assert_called_once_with("task-id")
    app.submit_command.assert_called_once_with(
        "active-segment",
        {"kind": action, "expected_revision": 3, "payload": {}},
        idempotency_key="original-intent",
    )
    app.resume_session.assert_not_called()
    app.suspend_session.assert_not_called()
