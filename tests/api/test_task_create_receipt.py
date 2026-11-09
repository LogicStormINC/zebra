from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from zebra_agent_api import task_routes
from zebra_agent_api.idempotency import TASK_CREATE_RECEIPT_PATH, scoped_idempotency_key
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteRequest

from tests.worker.test_task_binding_host_context import _context, _verified


def test_cloud_create_receipt_requires_current_authority_and_exact_scoped_key(monkeypatch):
    context = _context()
    verified = _verified(context)
    task = str(uuid4())
    app = Mock(settings=SimpleNamespace(deployment="cloud"))
    app.stores.idempotency.get.return_value = SimpleNamespace(
        status_code=201, response_body={"session_id": task, "prompt": "private"}
    )
    guard = Mock(return_value=None)
    monkeypatch.setattr(task_routes, "task_access_response", guard)

    def read(grant):
        return task_routes.handle_task_route(
            app,
            RouteRequest(
                "GET",
                TASK_CREATE_RECEIPT_PATH,
                headers={"Idempotency-Key": "original"},
                host_context=context,
                verified_host_grant=grant,
            ),
        )

    assert read(None).status_code == 403
    app.stores.idempotency.get.assert_not_called()
    response = read(verified)
    assert response.status_code == 200
    assert response.body == {"status": "accepted", "task_id": task}
    app.stores.idempotency.get.assert_called_once_with(
        action="session.create", idempotency_key=scoped_idempotency_key("original", context)
    )
    guard.assert_called_once_with(app, task, context, verified_host_grant=verified)
    guard.return_value = ApiResponse(404, {"task_id": task})
    assert read(verified).body == {"status": "create_receipt_unavailable"}
