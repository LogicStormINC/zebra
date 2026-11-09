"""The existing Task-control producer also obeys generic current-authority ceilings."""

import json

import jwt

from tests.host_grant_broker.test_current_authority import _headers, _setup


def body():
    return {
        "audience": "zebra",
        "threadId": "owned-thread",
        "taskControl": True,
        "scopes": ["agent.run"],
        "resourceRefs": [],
        "principal": {"userId": "opaque-user-1", "workspaceId": "workspace-1"},
    }


def test_generic_signed_task_control_uses_exact_body_and_no_run(monkeypatch):
    key, settings, _, seen, client = _setup(monkeypatch)
    payload = body()
    headers = _headers(payload)
    response = client.post("/exchange", json=payload, headers=headers)
    assert response.status_code == 200, response.json()
    claims = jwt.decode(
        response.json()["grant"],
        key.public_key(),
        algorithms=["RS256"],
        audience=settings.audience,
        issuer=settings.issuer,
    )
    assert claims["scopes"] == ["agent.run"]
    assert {(ref["type"], ref["id"]) for ref in claims["resource_refs"]} == {
        ("thread", "owned-thread"),
        ("principal", "opaque-user-1"),
    }
    assert len(seen) == 1 and json.loads(seen[0].content) == payload
    assert seen[0].headers["X-Zebra-Workload-Signature"] == headers["X-Zebra-Workload-Signature"]


def test_generic_task_control_cannot_exceed_current_rights(monkeypatch):
    _, _, rights, seen, client = _setup(monkeypatch)
    rights["scopes"] = []
    payload = body()
    response = client.post("/exchange", json=payload, headers=_headers(payload))
    assert response.status_code == 400 and response.json() == {
        "status": "rejected",
        "reason": "authority_scope_not_allowed",
    }
    assert len(seen) == 1


def test_generic_task_control_rejects_foreign_namespace(monkeypatch):
    _, _, rights, seen, client = _setup(monkeypatch)
    rights["namespaceId"] = "foreign-namespace"
    payload = body()
    response = client.post("/exchange", json=payload, headers=_headers(payload))
    assert response.status_code == 401
    assert response.json() == {"status": "rejected", "reason": "authority_identity_mismatch"}
    assert len(seen) == 1
