"""Generic API + real PostgreSQL control channel; no model, network or ERP adapter."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import SessionStatus
from agent_storage import PostgresLeaseStore
from agent_storage.postgres.leases import assert_current_lease_fence, lock_session_lease_boundary
from agent_storage.postgres.projections import PostgresProjectionStore
from zebra_agent_api import RouteAdapter

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_direct_control import _rows
from tests.agent_storage.test_postgres_direct_control_api import _app, _request
from tests.agent_storage.test_postgres_runtime_instances import _setup

postgres_dsn = _pg_fixture
dsn = _dsn_fixture


def _force(sid, key="force-once", **kwargs):
    return replace(_request(sid, key=key, **kwargs), body={"force": True})


def _progress(sid):
    return replace(_request(sid), method="GET", path=f"/tasks/{sid}/stop")


def test_force_api_accepts_and_fences_even_while_event_and_session_locks_are_held(dsn):
    lease = _setup(dsn)
    adapter = RouteAdapter(_app(dsn))
    events = _rows(dsn, "session_events")
    assert adapter.handle(_progress(lease.session_id)).body["state"] == "not_requested"
    with ThreadPoolExecutor(max_workers=1) as pool, psycopg.connect(dsn) as blocker:
        lock_session_lease_boundary(blocker, NAMESPACE, lease.session_id)
        blocker.execute(
            "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
            "AND session_id=%s FOR UPDATE",
            (NAMESPACE, lease.session_id),
        )
        try:
            response = pool.submit(adapter.handle, _force(lease.session_id)).result(timeout=5)
            assert response.status_code == 202, response.body
            assert response.body["request_accepted"]
            assert not response.body["resources_released"]
            projection = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
            assert projection.get_session_status(lease.session_id) is SessionStatus.CANCELLED
            leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
            assert leases.get(lease.session_id) is None
            with psycopg.connect(dsn) as writer, pytest.raises(LeaseLostError):
                assert_current_lease_fence(writer, NAMESPACE, lease.session_id, lease.fence)
        finally:
            blocker.rollback()
    assert _rows(dsn, "session_events") == events
    assert adapter.handle(_progress(lease.session_id)).body == response.body


def test_duplicate_keys_preserve_stop_identity_and_each_gets_an_immutable_receipt(dsn):
    sid = _setup(dsn).session_id
    adapter = RouteAdapter(_app(dsn))
    first = adapter.handle(_force(sid))
    second = adapter.handle(_force(sid, key="another-key"))
    assert first.status_code == second.status_code == 202
    assert second.body == first.body
    assert adapter.handle(_force(sid)).body == first.body
    assert adapter.handle(_force(sid, key="another-key")).body == second.body
    receipts = [
        r for r in _rows(dsn, "control_plane_idempotency_records") if r["action"] == "force_stop"
    ]
    assert len(receipts) == 2
    assert len(_rows(dsn, "agent_safety_overrides")) == 1


def test_force_stop_denies_foreign_or_expired_authority_without_writing(dsn):
    sid = _setup(dsn).session_id
    adapter = RouteAdapter(_app(dsn))
    original = _request(sid).host_context
    for update in (
        {"namespace_id": "other-tenant"},
        {"workspace_ref": "other-workspace"},
        {"scopes": ["artifact.read"]},
        {
            "resource_refs": [
                *original.model_dump()["resource_refs"],
                {"type": "run", "id": "restricted-run"},
            ]
        },
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"resource_refs": [{"type": "principal", "id": "other-user"}]},
    ):
        context = original.model_validate({**original.model_dump(), **update})
        denied = 404 if "namespace_id" in update or "workspace_ref" in update else 403
        assert adapter.handle(_force(sid, context=context)).status_code == denied
        request = _request(sid, context=context)
        assert (
            adapter.handle(replace(request, method="GET", path=f"/tasks/{sid}/stop")).status_code
            == denied
        )
    assert adapter.handle(replace(_force(sid), verified_host_grant=None)).status_code == 403
    forged = _force(sid)
    forged = replace(
        forged,
        verified_host_grant=replace(
            forged.verified_host_grant, authority_issuer="https://other-issuer.example"
        ),
    )
    assert adapter.handle(forged).status_code in {403, 404}
    assert _rows(dsn, "agent_safety_overrides") == []


def test_same_key_cannot_stop_a_different_task(dsn):
    first, second = _setup(dsn).session_id, _seed(dsn).session_id
    adapter = RouteAdapter(_app(dsn))
    assert adapter.handle(_force(first)).status_code == 202
    assert adapter.handle(_force(second)).status_code == 409
    assert adapter.handle(_progress(second)).body["state"] == "not_requested"


def test_force_body_validation_does_not_mutate_task(dsn):
    sid = _setup(dsn).session_id
    adapter = RouteAdapter(_app(dsn))
    bad = replace(_force(sid), body={"force": True, "session_id": "foreign"})
    assert adapter.handle(bad).status_code == 400
    assert adapter.handle(_force(sid, key=None)).status_code == 400
    assert _rows(dsn, "agent_safety_overrides") == []


def test_non_erp_business_host_uses_the_same_native_api(dsn):
    from agent_core.application.session_bootstrap import (
        SessionBootstrapCommand,
        SessionBootstrapService,
    )
    from agent_core.application.workspace_projection import rebuild_workspace
    from agent_core.domain.task_bindings import host_context_digest
    from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
    from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction

    from tests.agent_storage.test_command_wakeup import _binding

    base = _binding("unused")
    context = base.host_capability.host_context.model_copy(
        update={"host_app_id": "inventory-portal"}
    )
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="generic business control",
            user_input="no execution requested",
            workspace_root="/tmp/no-runtime-used",
            host_context=context,
        )
    )
    sid = bootstrap.session.session_id
    capability = base.host_capability.model_copy(
        update={
            "host_app_id": context.host_app_id,
            "connector_id": context.host_app_id,
            "host_context": context,
            "grant_digest": host_context_digest(context),
        }
    )
    binding = base.model_copy(update={"task_id": str(sid), "host_capability": capability})
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
        TaskAdmissionRequest(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=binding,
        )
    )
    adapter = RouteAdapter(_app(dsn))
    response = adapter.handle(_force(sid, context=context))
    assert response.status_code == 202, response.body
    request = replace(
        _progress(sid),
        host_context=context,
        verified_host_grant=_request(sid, context=context).verified_host_grant,
    )
    assert adapter.handle(request).body == response.body


def test_other_safety_writers_cannot_erase_an_accepted_user_stop(dsn):
    from agent_storage.postgres.safety_overrides import PostgresSafetyOverrideStore

    sid = _setup(dsn).session_id
    adapter = RouteAdapter(_app(dsn))
    accepted = adapter.handle(_force(sid))
    assert accepted.status_code == 202
    with psycopg.connect(dsn) as connection:
        safety = PostgresSafetyOverrideStore(connection)
        for shadow in (False, True):
            failure = safety.record_failure(
                namespace=NAMESPACE,
                session_id=str(sid),
                reason="another recovery error",
                structural=True,
                max_attempts=1,
                shadow=shadow,
            )
            assert failure.reason == "user_force_stop" and not failure.shadow
            for kind in ("dead_letter", "zombie_repair", "watchdog"):
                final = safety.finalize(
                    namespace=NAMESPACE,
                    session_id=str(sid),
                    kind=kind,
                    reason="another safety action",
                    diagnostics="legacy plain text",
                    shadow=shadow,
                )
                assert final.reason == "user_force_stop" and final.kind == "watchdog"
        other = _seed(dsn).session_id
        projection = PostgresProjectionStore(dsn, deployment_namespace=NAMESPACE)
        original = projection.get_session_status(other)
        safety.finalize(
            namespace=NAMESPACE,
            session_id=str(other),
            kind="watchdog",
            reason="unrelated",
            diagnostics="legacy plain text",
            shadow=False,
        )
        connection.commit()
        assert projection.get_session_status(other) is original
    assert adapter.handle(_progress(sid)).body == accepted.body
    assert PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).get(sid) is None
