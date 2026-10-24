"""Public validation fails closed before any original dispatch."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api import client_admission_operations as api


def test_sqlite_new_contract_disabled_legacy_surface_unchanged(tmp_path):
    adapter = RouteAdapter(create_app(tmp_path / "legacy.sqlite"))
    response = adapter.handle(RouteRequest("POST", f"/v1/admission-operations/{uuid4()}", body={}))
    assert response.status_code == 503


@pytest.mark.parametrize(
    "method,body,query,expected",
    [
        ("GET", {}, None, 400),
        ("GET", None, {"key": "secret"}, 400),
        ("DELETE", None, None, 405),
    ],
)
def test_observation_never_accepts_write_input(method, body, query, expected):
    request = RouteRequest(method, f"/v1/admission-operations/{uuid4()}", body=body, query=query)
    response = api.handle_admission_operation(SimpleNamespace(), request)
    assert response.status_code == expected


def test_utf8_hash_contract_vector():
    assert api._request_hash({"payload": {"prompt": "用户 <详情> & 执行", "execute": False}}) == (
        "231afb24a8f9e7c791fd7c56ed76e14e2aaa19b89c15a9120d943c20765b29f0"
    )


@pytest.mark.parametrize("value", [1.5, 1.0, 9007199254740992, {"nested": [1.5]}])
def test_unportable_numbers_rejected(value):
    with pytest.raises(ValueError):
        api._bounded_numbers(value)


def test_task_creation_uses_full_original_authority_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "create_task", lambda *args, **kwargs: calls.append(kwargs) or None)
    body = api.Admission(kind="task_create", payload={"execute": False})
    request = RouteRequest("POST", "/unused")
    for scope in ("first-thread-issuer", "second-thread-issuer"):
        api._dispatch(None, request, body, scope)
    assert calls[0]["idempotency_key"] != calls[1]["idempotency_key"]
    assert calls[0]["idempotency_key"] == "admission-v1:first-thread-issuer"


def test_observation_endpoint_cannot_dispatch_post():
    request = RouteRequest("POST", f"/v1/admission-operations/{uuid4()}/observation", body={})
    assert api.handle_admission_operation(SimpleNamespace(), request).status_code == 405


@pytest.mark.parametrize("body,query", [({}, None), (None, {"replay": "true"})])
def test_termination_rejects_input_before_storage(body, query):
    request = RouteRequest(
        "POST", f"/v1/admission-operations/{uuid4()}/termination", body=body, query=query
    )
    assert api.handle_admission_operation(SimpleNamespace(), request).status_code == 400


def test_atomic_surface_never_silently_admits_task_creation():
    request = RouteRequest(
        "POST",
        "/unused",
        headers={"X-Zebra-Admission-Protocol": "atomic-surface/1"},
        body={"kind": "task_create", "payload": {"execute": False}},
    )
    app = SimpleNamespace(stores=SimpleNamespace(idempotency=SimpleNamespace(get=lambda **k: None)))
    assert api._handle(app, request, str(uuid4()), "owned", bytes(range(32))).status_code == 400


@pytest.mark.parametrize(
    "extra",
    [
        {"execute": True},
        {"attachments": [{"text": "x"}]},
        {"workspace_source": {"kind": "git"}},
        {"mcp_resource_ids": ["server:resource"]},
        {"mcp_prompt_id": "server:prompt"},
        {"coverage_admission": {}},
    ],
)
def test_atomic_task_rejects_external_effects_before_ports(extra):
    from zebra_agent_api.client_admission_task import validate_atomic_task

    body = api.Admission(kind="task_create", payload={"execute": False, **extra})
    with pytest.raises(ValueError):
        validate_atomic_task(SimpleNamespace(), body)
