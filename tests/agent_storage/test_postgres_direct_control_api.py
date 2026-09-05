"""Actual composed PG authority for public Task cancellation; no runtime IO."""

from dataclasses import replace
from uuid import uuid4

import pytest
from agent_integrations.acp import AcpEntryAdapter
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_config import load_settings
from zebra_agent_worker.control import SessionControlError, SessionControlService

from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_direct_control import _rows
from tests.agent_storage.test_postgres_runtime_instances import SCOPE, _setup
from tests.test_cloud_api_worker_profile_composition import _cloud_settings

dsn = _dsn_fixture
postgres_dsn = _pg_fixture


def _app(dsn):
    # A deliberate unreachable settings DSN: both guard and mutation MUST use CloudComposition.
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": "cloud",
            "ZEBRA_DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )
    cloud = replace(
        _cloud_settings(),
        dsn=dsn,
        deployment_namespace=NAMESPACE,
        history_scope=SCOPE,
        continuation_scope=SCOPE,
    )
    return create_app(settings=settings, cloud_composition=cloud)


def _request(session, *, key=None, context=None, action="cancel"):
    return RouteRequest(
        "POST",
        f"/tasks/{session}/{action}",
        body={},
        headers=None if key is None else {"Idempotency-Key": key},
        host_context=context or _binding(str(session)).host_capability.host_context,
    )


def test_actual_task_cancel_uses_composed_dsn_and_preserves_200_and_replay(dsn):
    lease = _setup(dsn)
    adapter = RouteAdapter(_app(dsn))
    result = adapter.handle(_request(lease.session_id, key="cancel-retry"))
    assert result.status_code == 200, result.body
    assert result.body["cancelled"] is True
    assert result.body["task_id"] == result.body["session_id"] == str(lease.session_id)
    assert result.body["workspace_status"] == "cancelled"
    before = _rows(dsn, "session_events")
    repeated = adapter.handle(_request(lease.session_id, key="cancel-retry"))
    assert repeated == result
    assert _rows(dsn, "session_events") == before
    assert adapter.handle(_request(lease.session_id)).status_code == 409
    other = _seed(dsn)
    assert adapter.handle(_request(other.session_id, key="cancel-retry")).status_code == 409
    assert adapter.handle(_request(uuid4())).status_code == 404


@pytest.mark.parametrize("change", ["tenant", "principal", "permission", "workspace"])
def test_task_caller_scope_and_permission_reject_without_any_mutation(dsn, change):
    lease = _setup(dsn)
    context = _binding(str(lease.session_id)).host_capability.host_context
    updated = context.model_dump(mode="json")
    updated.update(
        {"namespace_id": "wrong"}
        if change == "tenant"
        else {"resource_refs": [{"type": "principal", "id": "wrong"}]}
        if change == "principal"
        else {"scopes": ["artifact.read"]}
        if change == "permission"
        else {"workspace_ref": "wrong"}
    )
    context = type(context).model_validate(updated)
    before = _rows(dsn, "session_events"), _rows(dsn, "worker_leases")
    response = RouteAdapter(_app(dsn)).handle(_request(lease.session_id, context=context))
    assert response.status_code in (404, 409)
    assert (_rows(dsn, "session_events"), _rows(dsn, "worker_leases")) == before
    assert not _rows(dsn, "command_runtime_cleanup")


def test_cloud_suspend_is_explicit_unsupported_without_runtime_mutation(dsn):
    lease = _setup(dsn)
    before = _rows(dsn, "session_events"), _rows(dsn, "worker_leases")
    response = RouteAdapter(_app(dsn)).handle(_request(lease.session_id, action="suspend"))
    assert response.status_code == 409
    assert response.body["reason"] == "cloud_user_suspend_is_unsupported"
    assert (_rows(dsn, "session_events"), _rows(dsn, "worker_leases")) == before


def test_explicit_stores_without_matching_direct_composition_fail_closed(dsn, tmp_path):
    lease = _setup(dsn)
    app = _app(dsn)
    service = SessionControlService(tmp_path, stores=app.stores)
    with pytest.raises(SessionControlError, match="explicit composition"):
        service.cancel_session(lease.session_id, scope=SCOPE)
    assert not _rows(dsn, "direct_control_operations")


def test_generic_acp_uses_explicit_control_scope_not_read_scope(dsn):
    import psycopg

    lease = _setup(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("DELETE FROM task_binding_snapshots")
    app = _app(dsn)
    ref = f"acp:{lease.session_id}"
    assert AcpEntryAdapter(app).cancel(ref).status_code == 409
    trusted = AcpEntryAdapter(app, trusted_control_scope=SCOPE)
    result = trusted.cancel(ref, idempotency_key="acp-retry")
    assert result.status_code == 200
    assert trusted.cancel(ref, idempotency_key="acp-retry") == result


@pytest.mark.parametrize("key", ["", "secret-marker-" + "a" * 256])
def test_invalid_header_rejected_without_reflecting_or_persisting_value(dsn, key):
    lease = _setup(dsn)
    before = _rows(dsn, "session_events"), _rows(dsn, "worker_leases")
    response = RouteAdapter(_app(dsn)).handle(_request(lease.session_id, key=key))
    assert response.status_code == 409
    assert response.body["reason"] == "invalid_direct_cancellation_idempotency_key"
    assert (_rows(dsn, "session_events"), _rows(dsn, "worker_leases")) == before
    assert not _rows(dsn, "direct_control_operations")
