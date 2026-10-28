from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from zebra_agent_api.host_memory_scope import host_memory_response


def request(method="GET", suffix=(), body=None):
    context = HostContextEnvelope(
        grant_id="a",
        limits=HostTechnicalLimits(
            max_runtime_seconds=300, max_model_tokens=1000, max_artifact_bytes=1024
        ),
        host_app_id="generic",
        namespace_id="team-a",
        workspace_ref="company-private-workspace",
        origin="https://host.example",
        resource_refs=(HostResourceRef(type="principal", id="person"),),
        scopes=("agent.run",),
        policy_version="v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    return SimpleNamespace(host_context=context, method=method, body=body), (
        "person",
        "memory",
        *suffix,
    )


def test_inventory_is_scoped_before_read_and_never_replays_events():
    stores = SimpleNamespace(memories=Mock(), events=Mock())
    from agent_core.domain.identifiers import new_memory_id
    from agent_core.domain.memories import MemoryRecord, MemoryType, MemoryVisibility

    now = datetime.now(UTC)
    stores.memories.list.return_value = [
        MemoryRecord(
            memory_id=new_memory_id(),
            memory_type=MemoryType.PREFERENCE,
            text="prefer concise replies",
            confidence=1,
            visibility=MemoryVisibility.USER,
            user_id="person",
            repo_id="company-private-workspace",
            tenant_id="team-a",
            created_at=now,
            updated_at=now,
        )
    ]
    req, parts = request()
    response = host_memory_response(SimpleNamespace(stores=stores), req, "user", parts)
    assert response.status_code == 200
    assert response.body["memories"][0]["text"] == "prefer concise replies"
    query = stores.memories.list.call_args.args[0]
    assert (query.repo_id, query.user_id, query.tenant_id) == (
        "company-private-workspace",
        "person",
        "team-a",
    )
    stores.events.list_for_session.assert_not_called()


@pytest.mark.parametrize("field", ["repo_id", "user_id", "tenant_id"])
@pytest.mark.parametrize("method", ["PATCH", "DELETE", "POST"])
def test_foreign_record_cannot_be_edited_confirmed_or_deleted(field, method):
    record = SimpleNamespace(
        repo_id="company-private-workspace", user_id="person", tenant_id="team-a"
    )
    setattr(record, field, "foreign")
    stores = SimpleNamespace(memories=Mock())
    stores.memories.get.return_value = record
    suffix = (str(uuid4()), "confirm") if method == "POST" else (str(uuid4()),)
    req, parts = request(method, suffix)
    assert (
        host_memory_response(SimpleNamespace(stores=stores), req, "user", parts).status_code == 403
    )


def test_create_refuses_foreign_source_before_write(monkeypatch):
    from zebra_agent_api.responses import ApiResponse

    monkeypatch.setattr(
        "zebra_agent_api.memory_routes.task_access_response", lambda *_: ApiResponse(404, {})
    )
    create = Mock()
    monkeypatch.setattr("zebra_agent_api.host_memory_scope.create_user_memory", create)
    req, parts = request("POST", body={"source_task_id": str(uuid4()), "text": "preference"})
    from zebra_agent_api.memory_routes import handle_memory_route
    from zebra_agent_api.routes import RouteRequest

    assert (
        handle_memory_route(
            SimpleNamespace(stores=Mock()),
            RouteRequest(
                method=req.method,
                path="/users/person/memory",
                body=req.body,
                host_context=req.host_context,
            ),
        ).status_code
        == 404
    )
    create.assert_not_called()


def test_bulk_and_tenant_routes_cannot_bypass_workspace():
    req, parts = request("POST", ("bulk-review",))
    assert host_memory_response(Mock(), req, "user", parts).status_code == 403
    req, parts = request()
    assert host_memory_response(Mock(), req, "tenant", parts).status_code == 403
