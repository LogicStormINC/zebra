"""Owned actual PG Task/Surface/Worker composition for revision-two HTTP gates."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from agent_core.application.mock_model import ScriptedModelGateway
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.identifiers import TaskId
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
from agent_integrations.ag_ui.standard_profiles import standard_profiles
from agent_storage.postgres.client_effects import (
    PostgresClientEffectDispatch,
    PostgresClientEffectReceipts,
)
from agent_storage.postgres.task_admission import load_task_binding
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_worker import SessionClaimService, SessionExecutionService, SessionResumeService
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
from zebra_agent_worker.client_effect_runtime import compose_client_runtime
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.execution_storage import compose_recovery
from zebra_agent_worker.provider_continuation_commit import CloudProviderContinuationCoordinator
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator

from tests.api.test_agui_initial_native import initial_native
from tests.worker.execution.worker_execution_support import _settings


def native_fixture(
    dsn, tmp_path, monkeypatch, responses, *, frontend_profile=None, profile_id="agui-standard-1.0"
):
    app, initial_request, _, original, message = initial_native(
        dsn, tmp_path, mounted_actions=("app.ui.item.open",), frontend_profile=frontend_profile
    )
    stores = app.stores
    namespace = stores.deployment_namespace
    task = TaskId(UUID(original["task_id"]))
    run = initial_request.body["run"]
    platform = replace(
        app.client_platform,
        client_effects=PostgresClientEffectDispatch(dsn, deployment_namespace=namespace),
        client_effect_receipts=PostgresClientEffectReceipts(dsn, deployment_namespace=namespace),
    )
    app = replace(
        app,
        client_platform=platform,
        agui_profiles=AgUiProfileRegistry(standard_profiles(interactions=True)),
    )
    mount = {
        **initial_request.body["payload"]["surface"]["mount"],
        "client_session_id": original["surface"]["client_session_id"],
        "ui_revision": 2,
        "mounted_actions": ["app.ui.item.open"],
        "mounted_at": datetime.now(UTC).isoformat(),
    }
    headers = {"X-Zebra-Client-Session": original["surface"]["session_credential"]}
    mounted = RouteAdapter(app).handle(
        RouteRequest(
            "POST",
            f"/v1/tasks/{task}/runs/{run}/client-surface",
            headers=headers,
            body={
                "mount": mount,
                "task_capability_scope": ["app.ui.item.open"],
                "controller": True,
            },
            host_context=initial_request.host_context,
            verified_host_grant=initial_request.verified_host_grant,
        )
    )
    assert mounted.status_code == 201, mounted.body
    headers.update(
        {
            "X-Zebra-Client-Fence": mounted.body["controller_fence_token"],
            "X-Zebra-Command-Segment": str(task),
            "X-Zebra-AGUI-Profile": profile_id,
            "X-Zebra-AGUI-Revision": "2",
        }
    )
    forwarded = {
        "clientStateVersion": 1,
        "frontendAppId": mount["frontend_app_id"],
        "clientSessionId": mount["client_session_id"],
        "uiRevision": 2,
        "profileDigest": mounted.body["profile_digest"],
        "mountedSnapshotDigest": mounted.body["mounted_snapshot_digest"],
        "clientBindingDigest": mounted.body["binding_digest"],
    }
    from agent_storage import S3ArtifactObjectStore

    from tests.agent_storage.test_s3_artifact_objects import _FakeS3Client

    objects = S3ArtifactObjectStore(_FakeS3Client(), bucket="agui-fixture")
    settings = replace(
        _settings(tmp_path / "unused-worker.sqlite"), profile="cloud", database_url=dsn
    )
    gateway = ScriptedModelGateway(tuple(responses))
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway", lambda settings: gateway
    )

    def consumer():
        transaction = stores.worker_projection_transaction
        _, _, recovery = compose_recovery(stores, transaction, namespace, None)
        claim = SessionClaimService(stores.leases, recovery)
        frozen = load_task_binding(dsn, deployment_namespace=namespace, task_id=task)
        authority = BoundHostExecutionAuthorityResolver(frozen)

        def provider_continuation(session):
            return CloudProviderContinuationCoordinator(
                store=stores.provider_continuations,
                session_id=session,
                scope=OpaqueAuthorityScope(
                    authority_issuer=initial_request.verified_host_grant.authority_issuer,
                    namespace_id=initial_request.host_context.namespace_id,
                    allowed_session_ids=(str(session),),
                ),
            )

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
                session, stores.artifact_payloads, objects
            ),
            execution_authority_resolver=authority,
            execution_authority_scope=authority.scope,
            task_binding_loader=lambda session: load_task_binding(
                dsn, deployment_namespace=namespace, task_id=task
            ),
            client_runtime=compose_client_runtime(
                dsn, deployment_namespace=namespace, enabled=True
            ),
            cloud_provider_continuation_factory=provider_continuation,
        )
        return SessionCommandConsumer(stores, execution)

    def request(method, suffix, *, body=None, operation=None, extra=None):
        return RouteAdapter(app).handle(
            RouteRequest(
                method,
                f"/agui/threads/{task}/runs/{run}/{suffix}",
                body=body,
                headers={
                    **headers,
                    **({"Idempotency-Key": str(operation)} if operation else {}),
                    **(extra or {}),
                },
                host_context=initial_request.host_context,
                verified_host_grant=initial_request.verified_host_grant,
            )
        )

    return app, task, run, initial_request, original, headers, forwarded, gateway, consumer, request


def official_http_gate(app, initial_request, headers, locators, dsn, tmp_path, monkeypatch):
    """Run real signed HTTP against the actual PG producer and official TS client."""
    import json
    import os
    import subprocess
    from pathlib import Path
    from threading import Thread
    from time import monotonic, sleep

    import uvicorn
    from agent_security import PyJwtHostGrantDecoder
    from agent_storage import HostRegistryRecord, PostgresHostAuthorityStore
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
    from zebra_agent_api.http import create_http_app
    from zebra_agent_api.stream_v2_authority import V2ReadAuthority
    from zebra_agent_api.stream_v2_reader import StreamV2Reader

    from tests.api.test_postgres_host_auth_authorizer import _StaticResolver

    context = initial_request.host_context
    verified = initial_request.verified_host_grant
    namespace = app.stores.deployment_namespace
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    registry = PostgresHostAuthorityStore(dsn, deployment_namespace=namespace)
    registry.upsert_registry(
        HostRegistryRecord(
            host_app_id=context.host_app_id,
            namespace_id=context.namespace_id,
            issuer=verified.authority_issuer,
            audience="agui-interaction-gate",
            jwks_uri=verified.authority_issuer + "/jwks",
            allowed_origins=(context.origin,),
            algorithms=("RS256",),
            policy_version=context.policy_version,
        )
    )
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry, decoder=PyJwtHostGrantDecoder(_StaticResolver(private.public_key()))
    )
    reader = StreamV2Reader(
        V2ReadAuthority(app.stores, dsn=dsn, namespace=namespace),
        url=os.environ["ZEBRA_STREAM_TEST_REDIS_URL"],
        key=b"r" * 32,
        live_prefix="agui-g5a-" + namespace,
    )
    app = replace(app, stream_v2_reader=reader)
    monkeypatch.setattr("zebra_agent_api.http.create_app", lambda *a, **k: app)
    http = create_http_app(
        tmp_path / "unused-http.sqlite",
        settings=app.settings,
        stores=app.stores,
        host_grant_authorizer=authorizer,
    )
    config = uvicorn.Config(http, host="127.0.0.1", port=0, log_level="error", access_log=False)
    sock = config.bind_socket()
    server = uvicorn.Server(config)
    serving = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    serving.start()
    deadline = monotonic() + 10
    while not server.started:
        assert monotonic() < deadline
        sleep(0.01)
    try:
        target = tmp_path / "native-interaction-metadata.json"
        target.write_text(
            json.dumps(
                {
                    "origin": f"http://127.0.0.1:{sock.getsockname()[1]}",
                    "taskId": headers["X-Zebra-Command-Segment"],
                    "run": initial_request.body["run"],
                    "profile": headers["X-Zebra-AGUI-Profile"],
                    "headers": headers,
                    "locators": locators,
                    "context": context.model_dump(mode="json"),
                    "issuer": verified.authority_issuer,
                    "subject": verified.subject_ref,
                    "privateKey": private.private_bytes(
                        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
                    ).decode(),
                }
            )
        )
        target.chmod(0o600)
        root = Path(__file__).parents[2]
        result = subprocess.run(
            [
                "pnpm",
                "--dir",
                str(root / "sdks/typescript"),
                "exec",
                "tsx",
                str(root / "tests/conformance/agui_contract/native_interaction_http_gate.mts"),
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, (result.stdout + result.stderr)[-12000:]
    finally:
        server.should_exit = True
        serving.join(timeout=10)
        sock.close()
        target.unlink(missing_ok=True)


def signed_test_client(app, initial, dsn, tmp_path, monkeypatch):
    """Existing Host authorizer with actual RSA signatures and native nonce store."""
    import jwt
    from agent_security import PyJwtHostGrantDecoder
    from agent_storage import HostRegistryRecord, PostgresHostAuthorityStore
    from cryptography.hazmat.primitives.asymmetric import rsa
    from fastapi.testclient import TestClient
    from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
    from zebra_agent_api.http import create_http_app

    from tests.api.test_postgres_host_auth_authorizer import _StaticResolver

    context, verified = initial.host_context, initial.verified_host_grant
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    registry = PostgresHostAuthorityStore(dsn, deployment_namespace=app.stores.deployment_namespace)
    registry.upsert_registry(
        HostRegistryRecord(
            host_app_id=context.host_app_id,
            namespace_id=context.namespace_id,
            issuer=verified.authority_issuer,
            audience="agui-dual-gate",
            jwks_uri=verified.authority_issuer + "/jwks",
            allowed_origins=(context.origin,),
            algorithms=("RS256",),
            policy_version=context.policy_version,
        )
    )
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry, decoder=PyJwtHostGrantDecoder(_StaticResolver(private.public_key()))
    )
    monkeypatch.setattr("zebra_agent_api.http.create_app", lambda *a, **k: app)
    client = TestClient(
        create_http_app(
            tmp_path / "unused-http.sqlite",
            settings=app.settings,
            stores=app.stores,
            host_grant_authorizer=authorizer,
        )
    )

    def signed(run, **overrides):
        from uuid import uuid4

        now = int(datetime.now(UTC).timestamp())
        claims = {
            "iss": verified.authority_issuer,
            "aud": "agui-dual-gate",
            "sub": verified.subject_ref,
            "jti": str(uuid4()),
            "iat": now - 1,
            "nbf": now - 1,
            "exp": now + 120,
            "host_app_id": context.host_app_id,
            "namespace_id": context.namespace_id,
            "workspace_ref": context.workspace_ref,
            "resource_refs": [
                {
                    "type": ref.resource_type,
                    "id": run if ref.resource_type == "run" else ref.resource_id,
                }
                for ref in context.resource_refs
            ],
            "scopes": list(context.scopes),
            "limits": context.limits.model_dump(),
            "origin": context.origin,
            "policy_version": context.policy_version,
            **overrides,
        }
        return {
            "Origin": context.origin,
            "Authorization": "Bearer " + jwt.encode(claims, private, algorithm="RS256"),
        }

    return client, signed


def public_state(app, task, run, profile_id="agui-standard-1.0"):
    from agent_core.ports.task_projection_checkpoints import ProjectionScope
    from agent_integrations.ag_ui.standard_checkpoint import load_standard

    profile = app.agui_profiles.select(profile_id, "2")
    from dataclasses import replace
    from time import monotonic, sleep

    from zebra_agent_worker.ag_ui_composition import configure_agui_projection_work

    settings = replace(
        app.settings,
        stream=replace(
            app.settings.stream, agui_profiles_enabled=True, agui_native_interaction_enabled=True
        ),
    )
    import os

    from agent_integrations import RedisCommittedEventPublisher

    publisher = RedisCommittedEventPublisher.from_url(
        os.environ["ZEBRA_STREAM_TEST_REDIS_URL"],
        deployment_namespace=app.stores.deployment_namespace,
        key_prefix="agui-g5a-" + app.stores.deployment_namespace,
    )
    service = configure_agui_projection_work(
        app.stores, settings, app.stores.deployment_namespace, publisher.fanout.publish_checkpoint
    )
    assert service is not None and len(service.consumers) == 10
    service.start()
    try:
        deadline = monotonic() + 45
        while True:
            native = app.stores.tasks.read_run_header(task, run)
            scope = ProjectionScope(
                app.stores.deployment_namespace,
                task,
                native.anchor.event_id,
                profile.checkpoint_version(),
            )
            head = app.stores.tasks.read_checkpoint_head(scope)
            if head is not None and head.through_sequence >= native.highwater:
                break
            assert monotonic() < deadline, "actual Worker projection queue did not converge"
            sleep(0.02)
    finally:
        service.close()
        publisher.fanout.close()
    native = app.stores.tasks.read_run_header(task, run)
    scope = ProjectionScope(
        app.stores.deployment_namespace, task, native.anchor.event_id, profile.checkpoint_version()
    )
    return load_standard(
        native.anchor.segment_id,
        lambda keys: app.stores.tasks.read_cells_at(scope, native.highwater + 1, keys),
        required=True,
        state_type=profile.state_type,
    )
