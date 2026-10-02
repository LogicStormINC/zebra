"""Cloud Client Run binding must compare the Host tenant, not the DB namespace."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import new_task_id
from zebra_agent_api.client_grant_auth import ClientAuthContext
from zebra_agent_api.client_sessions import bind_client_run


@pytest.mark.parametrize(
    ("session_namespace", "expected_status"),
    [("trench-prod", 201), ("other-tenant", 403), (None, 403)],
)
def test_cloud_binding_uses_session_tenant(
    session_namespace: str | None, expected_status: int
) -> None:
    task_id = new_task_id()
    stores = MagicMock()
    stores.tasks.get_task.return_value = SimpleNamespace(
        active_segment_id=uuid4(), namespace="zebra"
    )
    stores.sessions.get_session.return_value = (
        SimpleNamespace(namespace_id=session_namespace) if session_namespace is not None else None
    )
    app = SimpleNamespace(
        settings=SimpleNamespace(deployment="cloud"),
        stores=stores,
        client_platform=SimpleNamespace(client_sessions=object(), client_control_leases=object()),
    )
    admission = SimpleNamespace(
        binding=SimpleNamespace(
            binding_id=uuid4(),
            binding_revision=1,
            binding_digest="a" * 64,
            allowed_actions=(),
        ),
        lease=None,
        controller_fence=None,
    )
    with patch("zebra_agent_api.client_sessions.ClientBindingService") as service:
        service.return_value.bind_run.return_value = admission
        response = bind_client_run(
            app,
            str(task_id),
            "run-1",
            {},
            ClientAuthContext(client_session_id=uuid4()),
            SimpleNamespace(namespace_id="trench-prod"),
        )
        assert response.status_code == expected_status
        assert service.return_value.bind_run.call_count == (1 if expected_status == 201 else 0)
