from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from zebra_agent_api import task_approval as mod
from zebra_agent_api.responses import ApiResponse


def test_authorization_precedes_approval_storage(monkeypatch):
    denied = ApiResponse(403, {"reason": "denied"})
    monkeypatch.setattr(mod, "task_access_response", lambda *a, **k: denied)

    def forbidden(*args):
        raise AssertionError("unauthorized storage read")

    monkeypatch.setattr(mod, "task_approval", forbidden)
    request = SimpleNamespace(method="GET", body=None, host_context=None, verified_host_grant=None)
    assert (
        mod.handle_task_approval(SimpleNamespace(), request, str(uuid4()), "original-run") is denied
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator", "spoof"),
        ("arguments", {}),
        ("expected_revision", True),
        ("decision", "execute"),
    ],
)
def test_client_cannot_change_authority_or_command(field, value):
    body = dict(
        approval_event_id=str(uuid4()),
        expected_revision=85,
        tool_call_id="call",
        call_fingerprint="a" * 64,
        decision="approve",
    )
    body[field] = value
    with pytest.raises(ValidationError):
        mod.ApprovalDecisionBody.model_validate(body)
