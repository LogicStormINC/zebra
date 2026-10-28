"""Actual same-PG Task/Surface/RUN admission retains its captured initial user input."""

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from agent_core.domain.client_capabilities import FrontendCapabilityBinding
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_core.ports.platform_control_plane import AgentPlatformControlPlane
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
from agent_storage.postgres.client_control_leases import PostgresClientControlLeaseStore
from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres_composition import postgres_control_plane_stores
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.routes import RouteAdapter, RouteRequest

from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_projection_source_metadata import (
    metadata_dsn as _metadata_dsn,
)
from tests.api.test_client_runtime_api import _profile
from tests.api.test_host_auth_http import _cloud_settings
from tests.test_cloud_api_worker_profile_composition import _cloud_settings as _composition

metadata_dsn = _metadata_dsn


def initial_native(dsn: str, tmp_path: Path, *, captured: bool = True, wakeup: bool = False):
    namespace = "agui-initial-" + uuid4().hex
    bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    if wakeup:
        import psycopg

        with psycopg.connect(dsn) as connection:
            connection.execute(
                "INSERT INTO command_wakeup_rollouts (deployment_namespace,admission_enabled) "
                "VALUES (%s,TRUE)",
                (namespace,),
            )
    cloud = _composition()
    stores = postgres_control_plane_stores(
        dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=cloud.memory_cursor_signing_key,
        artifact_objects=cloud.artifact_objects,
        history_scope=cloud.history_scope,
        continuation_scope=cloud.continuation_scope,
    )
    profile = _profile()
    registry = PostgresClientCapabilityRegistry(dsn, deployment_namespace=namespace)
    registry.publish_profile(profile)
    context = _binding(str(uuid4())).host_capability.host_context
    run = str(uuid4())
    context = context.model_copy(
        update={"resource_refs": (*context.resource_refs, HostResourceRef(type="run", id=run))}
    )
    verified = VerifiedHostGrant(
        context, context.grant_id, JwtAlgorithm.RS256, context.origin, "user-a"
    )
    registry.save_binding(
        FrontendCapabilityBinding(
            binding_id=uuid4(),
            deployment_namespace=namespace,
            host_app_id=context.host_app_id,
            namespace_id=context.namespace_id,
            frontend_app_id=profile.frontend_app_id,
            revision=profile.revision,
            profile_digest=profile.profile_digest,
            binding_revision=1,
            bound_at=datetime.now(UTC),
        ),
        expected_binding_revision=0,
    )
    sessions = PostgresClientSessionRegistry(dsn, deployment_namespace=namespace)
    leases = PostgresClientControlLeaseStore(dsn, deployment_namespace=namespace)
    app = ZebraAgentApi(
        database_path=tmp_path / "unused.sqlite",
        settings=_cloud_settings(dsn),
        _stores=stores,
        client_platform=AgentPlatformControlPlane(
            deployment_namespace=namespace,
            frontend_capabilities=registry,
            client_sessions=sessions,
            client_control_leases=leases,
        ),
        cloud_control=PostgresDirectControl(dsn, deployment_namespace=namespace),
    )
    key = b"k" * 32
    message = {"id": "initial-captured", "role": "user", "content": "ACTUAL INITIAL USER MESSAGE"}
    body = {
        "kind": "task_create",
        "run": run,
        "payload": {
            "task": {
                "title": "AGUI initial",
                "prompt": message["content"],
                "workspace": str(tmp_path),
                "execute": True,
                "interaction_mode": "conversation",
            },
            "surface": {
                "grant": {
                    "grant_id": str(uuid4()),
                    "host_app_id": context.host_app_id,
                    "namespace_id": context.namespace_id,
                    "frontend_app_id": profile.frontend_app_id,
                    "origin": context.origin,
                    "user_ref": verified.subject_ref,
                    "profile_digest": profile.profile_digest,
                    "scopes": ["client.action"],
                    "expires_at": context.expires_at.isoformat(),
                },
                "mount": {
                    "frontend_app_id": profile.frontend_app_id,
                    "profile_revision": profile.revision,
                    "profile_digest": profile.profile_digest,
                    "ui_revision": 1,
                    "mounted_actions": [],
                    "mounted_readables": ["app.ui.route"],
                    "mounted_at": datetime.now(UTC).isoformat(),
                },
                "task_capability_scope": [],
                "controller": True,
            },
            "input": {"state": {}, **({"message": message} if captured else {})},
        },
    }
    operation = str(uuid4())
    request = RouteRequest(
        "POST",
        "/v1/admission-operations/" + operation,
        body=body,
        headers={
            "X-Zebra-Admission-Key": key.hex(),
            "X-Zebra-Admission-Protocol": "atomic-task-run-surface/1",
        },
        host_context=context,
        verified_host_grant=verified,
    )
    response = RouteAdapter(app).handle(request)
    assert response.status_code == 200 and response.body["status"] == "completed", response.body
    sealed = base64.b64decode(response.body["sealed_response"])
    original = json.loads(
        AESGCM(key).decrypt(sealed[:12], sealed[12:], response.body["request_hash"].encode())
    )
    assert response.body["response_status"] == 201, original
    return app, request, response, original, message


def test_initial_atomic_native_input_is_retained_once(metadata_dsn, tmp_path):
    app, request, receipt, original, message = initial_native(metadata_dsn, tmp_path)
    task = TaskId(UUID(original["task_id"]))
    source = app.stores.tasks.read_run_header(task, request.body["run"])
    assert source.anchor is not None
    events = app.stores.tasks.read_event_page(
        task, source.start - 1, limit=1, through_sequence=source.start
    )
    accepted = events.events[0].event
    assert accepted.payload["kind"] == "run"
    assert accepted.payload["payload"]["input"]["messages"] == [message]
    assert str(accepted.event_id) == original["command"]["event_id"]
    assert accepted.idempotency_key == original["command"]["idempotency_key"]
    assert accepted.event_id != UUID(original["command"]["command_id"])
    before = app.stores.tasks.read_task_header(task).current_sequence
    retry = RouteAdapter(app).handle(
        replace(
            request,
            method="GET",
            body=None,
            headers={**request.headers, "X-Zebra-Admission-Hash": receipt.body["request_hash"]},
        )
    )
    assert retry.body == receipt.body
    assert app.stores.tasks.read_task_header(task).current_sequence == before


def initial_and_followup_native(
    metadata_dsn, tmp_path, monkeypatch, *, followup_answer: str | None = None
):
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_storage.postgres.task_admission import load_task_binding
    from zebra_agent_worker import (
        SessionClaimService,
        SessionExecutionService,
        SessionResumeService,
    )
    from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
    from zebra_agent_worker.command_consumer import SessionCommandConsumer
    from zebra_agent_worker.execution_storage import compose_recovery
    from zebra_agent_worker.provider_continuation_commit import CloudProviderContinuationCoordinator
    from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator

    from tests.worker.execution.worker_execution_support import _assistant_only_gateway, _settings

    app, request, _, original, message = initial_native(metadata_dsn, tmp_path)
    stores = app.stores
    namespace = stores.deployment_namespace
    transaction = stores.worker_projection_transaction
    _, _, recovery = compose_recovery(stores, transaction, namespace, None)
    claim = SessionClaimService(stores.leases, recovery)
    # The isolated gate executes a no-tool fake provider with trusted-local runtime;
    # every event, lease, checkpoint and projection remains native PostgreSQL.
    settings = _settings(tmp_path / "unused-worker.sqlite")
    gateway = _assistant_only_gateway(settings=settings)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway", lambda settings: gateway
    )
    frozen = load_task_binding(
        metadata_dsn, deployment_namespace=namespace, task_id=TaskId(UUID(original["task_id"]))
    )
    authority = BoundHostExecutionAuthorityResolver(frozen)
    execution = SessionExecutionService(
        database_path=tmp_path / "unused-worker.sqlite",
        stores=stores,
        claim_service=claim,
        resume_service=SessionResumeService(claim),
        settings=settings,
        worker_projection_transaction=transaction,
        deployment_namespace=namespace,
        effect_dispatch=stores.effects,
        cloud_artifact_factory=lambda session: CloudToolOutputArtifactCoordinator(
            session, stores.artifact_payloads, _composition().artifact_objects
        ),
        execution_authority_resolver=authority,
        execution_authority_scope=authority.scope,
        task_binding_loader=lambda session: load_task_binding(
            metadata_dsn, deployment_namespace=namespace, task_id=TaskId(session)
        ),
        cloud_provider_continuation_factory=lambda session: CloudProviderContinuationCoordinator(
            store=stores.provider_continuations,
            scope=OpaqueAuthorityScope(
                authority_issuer=request.verified_host_grant.authority_issuer,
                namespace_id=request.host_context.namespace_id,
                allowed_session_ids=(str(session),),
            ),
            session_id=session,
        ),
    )
    consumption = SessionCommandConsumer(stores, execution).consume_once(
        worker_id="agui-native-initial", lease_ttl_seconds=30
    )
    assert consumption.status == "executed", consumption
    assert message["content"] in repr(gateway.requests)
    assert len(gateway.requests) == 1
    task = TaskId(UUID(original["task_id"]))
    assert stores.tasks.read_run_header(task, request.body["run"]).anchor is not None
    # A fresh surfaced native Run on the same conversation Task owns the next
    # user MESSAGE. The original initial RUN/receipt remain untouched.
    from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
    from zebra_agent_api.routes import RouteRequest

    from tests.api.test_agui_public_slice import PROFILE

    app = replace(app, agui_profiles=AgUiProfileRegistry((PROFILE,)))
    next_run = str(uuid4())
    next_context = request.host_context.model_copy(
        update={
            "resource_refs": tuple(
                HostResourceRef(type="run", id=next_run) if ref.resource_type == "run" else ref
                for ref in request.host_context.resource_refs
            )
        }
    )
    verified = replace(request.verified_host_grant, context=next_context)
    metadata = original["surface"]
    mount = {
        **request.body["payload"]["surface"]["mount"],
        "client_session_id": metadata["client_session_id"],
        "ui_revision": 2,
        "mounted_at": datetime.now(UTC).isoformat(),
    }
    headers = {"X-Zebra-Client-Session": metadata["session_credential"]}
    mounted = RouteAdapter(app).handle(
        RouteRequest(
            "POST",
            f"/v1/tasks/{task}/runs/{next_run}/client-surface",
            body={"mount": mount, "task_capability_scope": [], "controller": True},
            headers=headers,
            host_context=next_context,
            verified_host_grant=verified,
        )
    )
    assert mounted.status_code == 201, mounted.body
    headers.update(
        {
            "X-Zebra-Client-Fence": mounted.body["controller_fence_token"],
            "X-Zebra-Command-Segment": str(task),
            "X-Zebra-AGUI-Profile": PROFILE.profile_id,
            "Idempotency-Key": str(uuid4()),
        }
    )
    from agent_core.domain.events import EventType

    initial_answer = next(
        event
        for event in stores.events.list_for_session(task)
        if event.event_type is EventType.ANSWER_COMMITTED
    )
    input_value = {
        "threadId": str(task),
        "runId": next_run,
        "protocolVersion": "1.0",
        "state": {"app.ui.route": {"note": "PRIVATE-READABLE-ONLY-A"}},
        "messages": [
            message,
            {
                "id": "message:answer:" + str(initial_answer.event_id),
                "role": "assistant",
                "content": "Worker completed the session.",
            },
            {
                "id": "followup-user",
                "role": "user",
                "content": "ACTUAL NATIVE FOLLOWUP USER MESSAGE",
            },
        ],
        "tools": [],
        "context": [],
        "forwardedProps": {
            "clientStateVersion": 1,
            "frontendAppId": mount["frontend_app_id"],
            "clientSessionId": metadata["client_session_id"],
            "uiRevision": 2,
            "profileDigest": mounted.body["profile_digest"],
            "mountedSnapshotDigest": mounted.body["mounted_snapshot_digest"],
            "clientBindingDigest": mounted.body["binding_digest"],
        },
    }
    prepared = RouteAdapter(app).handle(
        RouteRequest(
            "POST",
            f"/agui/threads/{task}/runs/{next_run}/prepare",
            body={
                "expectedRevision": stores.sessions.get_session(task).current_sequence,
                "input": input_value,
            },
            headers=headers,
            host_context=next_context,
            verified_host_grant=verified,
        )
    )
    assert prepared.status_code == 202, prepared.body
    if followup_answer is None:
        gateway = _assistant_only_gateway(settings=settings)
    else:
        from agent_core.application.mock_model import ScriptedModelGateway

        from tests.worker.execution.worker_execution_support import _final_response

        gateway = ScriptedModelGateway((_final_response(followup_answer),))
    consumption = SessionCommandConsumer(stores, execution).consume_once(
        worker_id="agui-native-followup", lease_ttl_seconds=30
    )
    assert consumption.status == "executed", consumption
    assert len(gateway.requests) == 1
    assert "ACTUAL NATIVE FOLLOWUP USER MESSAGE" in repr(gateway.requests)
    assert not (tmp_path / "unused-worker.sqlite").exists()

    return (
        app,
        next_context,
        verified,
        task,
        next_run,
        headers,
        input_value,
        gateway,
        original,
        request,
    )


def test_initial_native_input_reaches_worker_prompt(metadata_dsn, tmp_path, monkeypatch):
    initial_and_followup_native(metadata_dsn, tmp_path, monkeypatch)


def test_state_only_initial_rail_keeps_legacy_input_and_receipt_fields(metadata_dsn, tmp_path):
    app, request, _, original, _ = initial_native(metadata_dsn, tmp_path, captured=False)
    task = TaskId(UUID(original["task_id"]))
    run = app.stores.tasks.read_run_header(task, request.body["run"])
    page = app.stores.tasks.read_event_page(
        task, run.start - 1, limit=1, through_sequence=run.start
    )
    value = page.events[0].event.payload["payload"]["input"]
    assert set(value) == {"messages", "tools", "state", "forwardedProps"}
    assert value["messages"] == [] and value["tools"] == [] and value["state"] == {}
    assert set(original["command"]) == {"command_id", "status"}


def test_standard_post_reports_native_delivery_outcome_without_domain_terminal(
    metadata_dsn, tmp_path, monkeypatch
):
    import psycopg
    from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
    from agent_integrations.ag_ui.standard_profiles import standard_profiles
    from agent_storage.postgres.command_wakeup_outcome import PostgresCommandOutcomeReader
    from fastapi.testclient import TestClient
    from zebra_agent_api.http import create_http_app

    from tests.api.test_agui_reliable_native import materialize

    app, request, _, original, _ = initial_native(metadata_dsn, tmp_path, wakeup=True)
    task = TaskId(UUID(original["task_id"]))
    internal = request.body["run"]
    profile = standard_profiles()[0]
    from agent_core.application.session_projection import rebuild_session

    app.stores.sessions.save_session(rebuild_session(app.stores.events.list_for_session(task)))
    materialize(app.stores, task, internal, (profile,))
    reader = PostgresCommandOutcomeReader(
        metadata_dsn, deployment_namespace=app.stores.deployment_namespace
    )
    assert reader.supports_source_head(app.stores.tasks)
    app = replace(app, agui_profiles=AgUiProfileRegistry((profile,)), command_outcome=reader)
    context = request.host_context.model_copy(
        update={
            "resource_refs": (
                *request.host_context.resource_refs,
                HostResourceRef(type="task", id=str(task)),
            )
        }
    )
    verified = replace(request.verified_host_grant, context=context)

    class Authorizer:
        allowed_origins = (context.origin,)

        def authorize(self, call):
            call.before_consume(verified)
            return verified

    monkeypatch.setattr("zebra_agent_api.http.create_app", lambda *a, **k: app)
    # A missing outcome reader used to wait the full default 1800-second deadline.
    monkeypatch.setattr("zebra_agent_api.ag_ui_stream._MAX_STREAM_SECONDS", 1)
    client = TestClient(
        create_http_app(
            tmp_path / "unused-http.sqlite",
            settings=app.settings,
            stores=app.stores,
            host_grant_authorizer=Authorizer(),
        )
    )
    path = f"/agui/threads/{task}/runs/{internal}"
    headers = {
        "Authorization": "Bearer fixture-verified-grant",
        "Origin": context.origin,
        "X-Zebra-Client-Session": original["surface"]["session_credential"],
        "X-Zebra-Command-Segment": original["command"]["segment_id"],
        "X-Zebra-AGUI-Profile": profile.profile_id,
        "Idempotency-Key": original["command"]["idempotency_key"],
    }
    prepared = client.get(path + "/prepared", headers=headers)
    assert prepared.status_code == 200, prepared.text
    before = app.stores.events.list_for_session(task)
    assert not any(event.event_type.value == "turn_completed" for event in before)
    for recovery_code, expected in (
        (None, "command_delivery_failed"),
        ("recovery_exhausted", "command_recovery_exhausted"),
    ):
        with psycopg.connect(metadata_dsn) as connection:
            connection.execute(
                "UPDATE session_command_pending SET status='dead',recovery_code=%s "
                "WHERE deployment_namespace=%s AND command_id=%s",
                (recovery_code, app.stores.deployment_namespace, original["command"]["command_id"]),
            )
        anchor = app.stores.tasks.read_run_header(task, internal).anchor
        assert reader(task, internal, anchor.event_id, context) == expected
        response = client.post(path + "/stream", headers=headers, json=prepared.json()["input"])
        assert response.status_code == 200, response.text
        assert '"type":"RUN_STARTED"' in response.text
        assert '"code":"observation_unavailable"' in response.text
        assert response.text.count('"type":"RUN_ERROR"') == 1
        assert "RUN_FINISHED" not in response.text
        assert "zebra.observation.problem" not in response.text
        assert app.stores.events.list_for_session(task) == before
