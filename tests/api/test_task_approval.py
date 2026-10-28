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


@pytest.mark.parametrize("method,choice", [("GET", None), ("POST", "reject"), ("POST", "approve")])
@pytest.mark.parametrize("renewal_denied", [False, True])
def test_only_approved_wakeup_renews_verified_binding_first(
    monkeypatch, method, choice, renewal_denied
):
    calls = []
    grant = object()
    db = object()
    stores = SimpleNamespace(events=SimpleNamespace(_database=db))
    app = SimpleNamespace(stores=stores)
    body = (
        None
        if method == "GET"
        else dict(
            approval_event_id=str(uuid4()),
            expected_revision=85,
            tool_call_id="call",
            call_fingerprint="a" * 64,
            decision=choice,
        )
    )
    request = SimpleNamespace(
        method=method,
        body=body,
        query={},
        host_context=SimpleNamespace(host_app_id="host", namespace_id="ns"),
        verified_host_grant=grant,
    )
    monkeypatch.setattr(mod, "PostgresControlPlaneStores", SimpleNamespace)
    monkeypatch.setattr(mod, "task_access_response", lambda *a, **k: None)
    rejection = ApiResponse(403, {"status": "host_binding_renewal_rejected"})

    def renew(got_app, tid, verified):
        assert got_app is app and verified is grant
        calls.append("renew")
        return rejection if renewal_denied else None

    def decide(*args):
        calls.append("decision")
        return {"decision": choice}

    monkeypatch.setattr(mod, "renew_host_binding_for_command", renew)
    monkeypatch.setattr(mod, "task_approval", decide)
    result = mod.handle_task_approval(app, request, str(uuid4()), "original-run")
    if choice == "approve" and renewal_denied:
        assert result is rejection and calls == ["renew"]
    else:
        assert result.status_code == 200
        assert calls == (["renew", "decision"] if choice == "approve" else ["decision"])
