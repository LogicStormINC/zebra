"""Real PG expiry/takeover reaches Worker cancellation and native TLS teardown."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from functools import partial
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event, rebuild_session
from agent_core.application.workspace_projection import (
    apply_event as apply_workspace_event,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.tool_profiles import ToolProfile
from agent_runtime.crawl_gateway import CrawlGateway
from agent_storage import bootstrap_control_plane_epoch, postgres_control_plane_stores
from agent_storage.postgres.leases import (
    acquire_lease_in_transaction,
    assert_current_lease_fence,
    lock_session_lease_boundary,
)
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.execution_tool_gateway import build_execution_tool_gateway, extensions
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat, LeaseHeartbeatError
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.recovery import SessionRecoveryService
from zebra_agent_worker.tool_run_index import ToolRunIndexer
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory

from tests.agent_runtime.test_crawl_source_http import call, native_tls_source
from tests.agent_runtime.test_native_network_cancellation import (
    native_connect_proxy,
    observe_children,
)
from tests.api.test_postgres_host_auth_authorizer import dsn as _scratch_schema
from tests.test_cloud_api_worker_profile_composition import _cloud_settings
from tests.worker.execution.worker_execution_support import _settings
from tests.worker.test_cloud_context_materialization import _task

dsn = _scratch_schema


@pytest.fixture(scope="session")
def postgres_dsn():
    configured = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not configured:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to the owned header_scratch container")
    settings = conninfo_to_dict(configured)
    assert settings.get("dbname") == "header_scratch"
    assert settings.get("host") in {"127.0.0.1", "localhost"}
    assert settings.get("port") == "32786"
    return configured


@pytest.mark.parametrize("v2", [False, True])
def test_pg_expiry_takeover_stops_old_worker_and_rejects_publication(
    dsn, tmp_path, monkeypatch, v2
):
    namespace = f"network-cancel-{uuid4().hex}"
    cloud = _cloud_settings()
    stores = postgres_control_plane_stores(
        dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="PG network cancellation", user_input="Read", workspace_root=tmp_path
        )
    )
    session_id = bootstrap.session.session_id
    for event in bootstrap.events:
        stores.events.append(event)
    source = stores.events.list_for_session(session_id)
    session, workspace = rebuild_session(source), rebuild_workspace(source)
    stores.sessions.save_session(session)
    stores.workspaces.save_workspace(workspace)
    stores.tasks.ensure_for_session(session_id)
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    lease = stores.leases.acquire(
        session_id, owner_instance_id="old-worker", ttl=timedelta(seconds=1)
    )
    claims = SessionClaimService(
        stores.leases, SessionRecoveryService(stores.events, stores.sessions, stores.workspaces)
    )
    factory = WorkerProjectionRecorderFactory(
        stores=stores,
        model_call_indexer=ModelCallIndexer(stores.model_calls),
        tool_run_indexer=ToolRunIndexer(stores.tool_runs),
        transaction=stores.worker_projection_transaction,
        deployment_namespace=namespace,
    )
    settings = replace(_settings(tmp_path / "unused.sqlite"), web_pipeline_v2=v2)
    service = SimpleNamespace(
        _settings=settings,
        _session_history=stores.session_history,
        _artifact_payload_store=None,
        _egress_registry=None,
        _delegation_store=None,
        _deployment_namespace=namespace,
        _frozen_manifest_loader=None,
        _client_runtime=None,
        _extensions=extensions(None, None),
    )
    children = observe_children(monkeypatch)
    monkeypatch.setattr(
        "agent_runtime.web_tools.CrawlGateway",
        partial(CrawlGateway, resolver=lambda _host: ("93.184.216.34",)),
    )
    verified = False
    with (
        pytest.raises(LeaseHeartbeatError, match="worker Lease heartbeat failed") as exited,
        LeaseHeartbeat(claims, lease, lease_ttl_seconds=1) as heartbeat,
    ):
        recorder = factory.build(
            session=session,
            workspace=workspace,
            lease=lease,
            ownership_check=heartbeat.require_owned,
        )
        payload = {
            "schema_version": 1,
            "attempt_number": 1,
            "output_id": "public:old-worker",
            "kind": "status",
            "phase": "waiting",
            "origin": "system",
            "content": "No new confirmed result yet.",
            "status": "complete",
        }
        prepared = recorder.prepare(EventType.PUBLIC_OUTPUT, EventActor.HARNESS, payload)
        with native_connect_proxy(monkeypatch) as target:
            with native_tls_source(tmp_path, monkeypatch, "drip", on_listen=target.append) as (
                requests,
                entered,
                closed,
                release,
                writes,
            ):
                gateway = build_execution_tool_gateway(
                    service,
                    task=replace(_task(tmp_path), tool_profile=ToolProfile.GENERAL),
                    model_gateway=Mock(),
                    session_id=session_id,
                    runtime=Mock(),
                    runtime_handle=Mock(),
                    cloud_artifacts=None,
                    trusted_local=True,
                    task_binding=None,
                    materialized_context=None,
                    extension=None,
                    fence=lease.fence,
                    network_cancellation_check=recorder.require_active_execution,
                )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    native = executor.submit(gateway.execute, call("web.fetch"))
                    try:
                        assert entered.wait(2), (
                            native.result(timeout=1) if native.done() else "no TLS"
                        )
                        with psycopg.connect(dsn, row_factory=dict_row) as owner:
                            owner.execute("SET LOCAL statement_timeout='3s'")
                            lock_session_lease_boundary(owner, namespace, session_id)
                            assert_current_lease_fence(owner, namespace, session_id, lease.fence)
                            row = owner.execute(
                                "SELECT expires_at FROM worker_leases "
                                "WHERE deployment_namespace=%s "
                                "AND session_id=%s FOR UPDATE",
                                (namespace, session_id),
                            ).fetchone()
                            assert row is not None
                            # Real DB time expires while this row lock prevents renewal.
                            owner.execute(
                                "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM "
                                "(%s::timestamptz-clock_timestamp())))+0.01)",
                                (row["expires_at"],),
                            )
                            assert owner.execute(
                                "SELECT clock_timestamp() > %s AS expired", (row["expires_at"],)
                            ).fetchone()["expired"]
                            successor = acquire_lease_in_transaction(
                                owner,
                                namespace,
                                session_id,
                                owner_instance_id="new-worker",
                                ttl=timedelta(seconds=30),
                            )
                        assert successor.fence.fencing_token == lease.fence.fencing_token + 1
                        assert successor.fence.owner_instance_id == "new-worker"
                        stopped_at = monotonic()
                        with pytest.raises(LeaseHeartbeatError) as stopped:
                            native.result(timeout=1)
                        assert isinstance(stopped.value.__cause__, LeaseLostError)
                        assert closed.wait(0.5) and not release.is_set()
                        assert monotonic() - stopped_at < 1.5
                        assert len(requests) == 1 and writes
                        assert children and all(child.poll() is not None for child in children)
                        for child in children:
                            with pytest.raises(ChildProcessError):
                                os.waitpid(child.pid, os.WNOHANG)
                            assert child.stdout.closed and child.stdin.closed
                        with pytest.raises(LeaseHeartbeatError) as repeated:
                            gateway.execute(call("web.fetch"))
                        assert repeated.value is stopped.value and len(requests) == 1
                        with pytest.raises(LeaseHeartbeatError):
                            recorder.append_event(prepared)
                        # Independently prove the DB fence rejects even a preprepared Event.
                        with pytest.raises(LeaseLostError):
                            stores.worker_projection_transaction.commit_worker_event(
                                prepared,
                                apply_event(session, prepared),
                                apply_workspace_event(workspace, prepared),
                                authority=recorder.worker_mutation_authority,
                            )
                        assert stores.events.list_for_session(session_id) == source
                        with LeaseHeartbeat(
                            claims, successor, lease_ttl_seconds=1
                        ) as new_heartbeat:
                            new_recorder = factory.build(
                                session=session,
                                workspace=workspace,
                                lease=successor,
                                ownership_check=new_heartbeat.require_owned,
                            )
                            published = new_recorder.append(
                                EventType.PUBLIC_OUTPUT,
                                EventActor.HARNESS,
                                {**payload, "output_id": "public:new-worker"},
                            )
                        assert stores.events.list_for_session(session_id) == [*source, published]
                        verified = True
                    finally:
                        release.set()
                        gateway.close()
    assert verified, "expected heartbeat exit must not hide an unfinished native proof"
    assert exited.value.__cause__ is stopped.value.__cause__
