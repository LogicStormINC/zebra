"""Explicit renewal preserves authority without creating or replaying execution."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityResolutionRequest,
)
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.task_admission import (
    PostgresTaskAdmissionTransaction,
    load_task_binding,
    save_task_binding,
)
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_api.session_binding import _build_binding_snapshot, renew_task_binding_snapshot
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver

from tests.agent_storage.test_postgres_task_resource_binding import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_task_resource_binding import (
    postgres_dsn as _postgres_fixture,
)
from tests.api.ag_ui_checkpoint_fixture import PgGetReplay
from tests.api.test_extension_reads import AUTH
from tests.api.test_session_binding_renewal import _context, _verified
from tests.api.test_task_resource_binding import binding_for, verified
from tests.host_grant_broker.test_grant_broker import _key, _settings
from tests.test_cloud_api_worker_profile_composition import _cloud_settings

TASK = "11111111-1111-1111-1111-111111111111"
dsn = _dsn_fixture
postgres_dsn = _postgres_fixture


@pytest.fixture
def pg_get_replay(dsn, tmp_path):
    """Use real Broker resources; do not alter the shared observer fixture."""
    key = _key()
    grant = verified((key, _settings(key)), run="queued-renewal-run")
    cloud = replace(_cloud_settings(), dsn=dsn, deployment_namespace="resource-renewal-pg")
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued native renewal",
            user_input="read public facts",
            workspace_root=tmp_path,
            host_context=grant.context,
        )
    )
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=cloud.deployment_namespace).admit(
        TaskAdmissionRequest(
            events=bootstrap.events,
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=binding_for(grant, task=str(bootstrap.session.session_id)),
        )
    )
    return PgGetReplay(dsn, dsn, bootstrap.session.session_id, cloud, grant, tmp_path)


def _route(monkeypatch: pytest.MonkeyPatch):
    context = _context(grant_id="fresh")
    binding = _build_binding_snapshot(
        TASK,
        host_context=context,
        verified_host_grant=_verified(context),
        definition_snapshot_digest="a" * 64,
    )
    app = SimpleNamespace(
        settings=SimpleNamespace(
            deployment="cloud",
            storage_authority="postgresql",
            database_url="unused",
        ),
        stores=SimpleNamespace(
            deployment_namespace="renewal",
            sessions=SimpleNamespace(get_session=lambda _: None),
        ),
        cloud_control=SimpleNamespace(
            deployment_namespace="renewal",
            load_task_binding=lambda _: binding,
        ),
        submit_command=Mock(side_effect=AssertionError("renewal submitted execution")),
    )
    monkeypatch.setattr(
        "zebra_agent_api.session_binding.load_task_binding", lambda *_a, **_k: binding
    )
    save = Mock()
    monkeypatch.setattr("zebra_agent_api.session_binding.save_task_binding", save)
    return (
        app,
        RouteAdapter(cast(ZebraAgentApi, app)),
        RouteRequest(
            method="POST",
            path=f"/tasks/{TASK}/host-binding/renew",
            body={},
            host_context=context,
            verified_host_grant=_verified(context),
        ),
        save,
    )


def test_explicit_route_appends_binding_only(monkeypatch: pytest.MonkeyPatch) -> None:
    app, adapter, request, save = _route(monkeypatch)
    response = adapter.handle(request)
    assert response.status_code == 200 and response.body["status"] == "host_binding_renewed"
    save.assert_called_once()
    assert save.call_args.kwargs["expected_previous_revision"] == 1
    assert save.call_args.kwargs["binding"].binding_revision == 2
    app.submit_command.assert_not_called()


@pytest.mark.parametrize(
    "case,status",
    [
        ("method", 405),
        ("body", 400),
        ("unverified", 403),
        ("scope", 403),
        ("foreign_principal", 404),
        ("unsupported", 409),
    ],
)
def test_renewal_route_rejects_without_any_write(monkeypatch, case, status) -> None:
    app, adapter, request, save = _route(monkeypatch)
    if case == "method":
        request = replace(request, method="GET")
    elif case == "body":
        request = replace(request, body={"action": "run"})
    elif case == "unverified":
        request = replace(request, verified_host_grant=None)
    elif case in {"scope", "foreign_principal"}:
        assert request.host_context is not None
        context = request.host_context.model_copy(
            update=(
                {"scopes": ("trench:source:read",)}
                if case == "scope"
                else {
                    "resource_refs": tuple(
                        HostResourceRef(type="principal", id="user-2")
                        if ref.resource_type == "principal"
                        else ref
                        for ref in request.host_context.resource_refs
                    )
                }
            )
        )
        request = replace(request, host_context=context, verified_host_grant=_verified(context))
    else:
        app.settings.storage_authority = "sqlite"
    assert adapter.handle(request).status_code == status
    save.assert_not_called()
    app.submit_command.assert_not_called()


@pytest.mark.skipif(not os.getenv("ZEBRA_HEADER_SCRATCH_DSN"), reason="explicit isolated PG probe")
def test_native_queued_authority_renews_without_sse_or_execution(
    pg_get_replay: PgGetReplay,
) -> None:
    fixture = pg_get_replay
    stores = fixture.stores()
    stores.tasks.ensure_for_session(fixture.session)
    stores.workspaces.save_workspace(
        rebuild_workspace(list(stores.events.list_for_session(fixture.session)))
    )
    namespace, task = fixture.cloud.deployment_namespace, TaskId(fixture.session)
    current = load_task_binding(fixture.dsn, deployment_namespace=namespace, task_id=task)
    assert current is not None
    # A real accepted Run is durably queued; it is not an empty Task labelled
    # "queued". No Worker or observation GET executes it during this test.
    database = PostgresDatabase(fixture.dsn, deployment_namespace=namespace)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO command_wakeup_rollouts(deployment_namespace,admission_enabled) "
            "VALUES (%s,true)",
            (namespace,),
        )
    bootstrap_control_plane_epoch(fixture.dsn, deployment_namespace=namespace)
    session = stores.sessions.get_session(fixture.session)
    assert session is not None
    command = SessionCommand(
        session_id=fixture.session,
        kind=SessionCommandKind.RUN,
        expected_revision=session.current_sequence,
        idempotency_key="queued-renewal",
        payload={"run_id": "queued-renewal-run"},
    )
    accepted = stores.events.append(
        SessionEvent.create(
            session_id=fixture.session,
            sequence=session.current_sequence + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
        )
    )
    with database.connect() as connection:
        queued = connection.execute(
            "SELECT command_id,accepted_event_id,status,current_generation "
            "FROM session_command_pending WHERE deployment_namespace=%s "
            "AND accepted_event_id=%s",
            (namespace, accepted.event_id),
        ).fetchone()
        outbox = connection.execute(
            "SELECT message_id,status,wake_generation FROM broker_outbox "
            "WHERE deployment_namespace=%s",
            (namespace,),
        ).fetchall()
    assert queued is not None and queued["status"] == "pending"
    assert len(outbox) == 1 and outbox[0]["status"] == "pending"
    now = datetime.now(UTC)
    old_context = fixture.verified.context.model_copy(
        update={
            "grant_id": "expired-admission",
            "expires_at": now - timedelta(seconds=30),
        }
    )
    expired = renew_task_binding_snapshot(current, old_context, bound_at=now - timedelta(minutes=1))
    save_task_binding(
        fixture.dsn,
        deployment_namespace=namespace,
        binding=expired,
        expected_previous_revision=current.binding_revision,
    )
    request = ExecutionAuthorityResolutionRequest(
        session_id=fixture.session,
        attempt_number=1,
        scope=BoundHostExecutionAuthorityResolver(expired).scope,
        validated_at=now,
    )
    with pytest.raises(ExecutionAuthorityResolutionError, match="expired"):
        BoundHostExecutionAuthorityResolver(expired).resolve_for_attempt(request)
    before = stores.events.list_for_session(fixture.session)
    with replace(fixture, readonly_dsn=fixture.dsn).client() as client:
        response = client.post(
            f"/tasks/{fixture.session}/host-binding/renew", json={}, headers=AUTH
        )
    assert response.status_code == 200, response.text
    renewed = load_task_binding(fixture.dsn, deployment_namespace=namespace, task_id=task)
    assert renewed is not None and renewed.binding_revision == expired.binding_revision + 1
    snapshot = BoundHostExecutionAuthorityResolver(renewed).resolve_for_attempt(
        request.model_copy(update={"validated_at": datetime.now(UTC)})
    )
    assert snapshot.expires_at == renewed.host_capability.grant_expires_at
    assert renewed.agent_capability_ceiling == expired.agent_capability_ceiling
    assert renewed.host_capability.manifest_digest == expired.host_capability.manifest_digest
    assert stores.events.list_for_session(fixture.session) == before
    assert renewed.task_id == str(UUID(str(fixture.session)))
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT command_id,accepted_event_id,status,current_generation "
                "FROM session_command_pending WHERE deployment_namespace=%s "
                "AND accepted_event_id=%s",
                (namespace, accepted.event_id),
            ).fetchone()
            == queued
        )
        assert (
            connection.execute(
                "SELECT message_id,status,wake_generation FROM broker_outbox "
                "WHERE deployment_namespace=%s",
                (namespace,),
            ).fetchall()
            == outbox
        )
