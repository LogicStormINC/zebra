"""Strict composition boundaries; transport fixtures do not prove live origin."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_integrations.coverage_model_policy import MAX_METADATA_BYTES, MODELS_URL
from zebra_agent_worker.coverage_composition import load_official_model_policy

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    METADATA,
    dsn,
    model_cloud,  # noqa: F811
    postgres_dsn,
)


@pytest.fixture
def native_worker(
    model_cloud,  # noqa: F811
    monkeypatch,
    tmp_path,  # noqa: F811
    request,
):
    """Actual Worker/PG/model wire; Host DNS/connector and S3 are explicit fixtures."""
    from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

    import agent_integrations.host_tools.http as host_http
    import zebra_agent_worker.coverage_dispatch as dispatch
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_core.domain.events import EventType
    from agent_integrations.host_tools.contracts import HostWorkloadIdentity
    from agent_integrations.host_tools.gateway import HostToolGateway
    from agent_storage import (
        S3ArtifactObjectStore,
        artifact_object_reads,
        postgres_control_plane_stores,
    )
    from agent_storage.postgres.worker_replay_reader import PostgresWorkerReplayReader
    from botocore.awsrequest import AWSResponse
    from botocore.config import Config
    from botocore.session import Session
    from psycopg.conninfo import conninfo_to_dict
    from zebra_agent_config import load_settings
    from zebra_agent_worker import (
        SessionClaimService,
        SessionExecutionService,
        SessionResumeService,
    )
    from zebra_agent_worker.coverage_composition import CloudCoverageRuntime
    from zebra_agent_worker.execution_storage import compose_recovery
    from zebra_agent_worker.provider_continuation_commit import CloudProviderContinuationCoordinator
    from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator
    from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE
    from tests.worker.test_coverage_effect import SignedHost

    env = model_cloud
    env.native_object_sends = {"HEAD": 0, "GET": 0}

    def object_response(request, **kwargs):
        # Fixture bytes only; native signing/parser and scoped size/deadline checks remain.
        scope = artifact_object_reads.current_artifact_read_scope()
        assert scope is not None and scope.remaining() > 0
        assert request.method in {"HEAD", "GET"}
        env.native_object_sends[request.method] += 1
        assert b"AWS4-HMAC-SHA256" in request.headers["Authorization"]
        key = unquote(urlsplit(request.url).path).split("/", 2)[2]
        query = dict(parse_qsl(urlsplit(request.url).query))
        item = env.client._item({"Key": key, **({"VersionId": query["versionId"]}
                                               if "versionId" in query else {})})
        payload = item["Body"]
        assert len(payload) <= scope.max_bytes
        wire_body = payload if request.method == "GET" else b""
        assert len(wire_body) <= artifact_object_reads._BODY_LIMIT.get()
        headers = {
            "Content-Length": str(len(payload)),
            "Last-Modified": "Wed, 29 Jul 2026 00:00:00 GMT",
            "x-amz-version-id": item["VersionId"],
            **{f"x-amz-meta-{name}": value for name, value in item["Metadata"].items()},
        }
        scope.remaining()
        return AWSResponse(request.url, 200, headers, artifact_object_reads._RawBody(wire_body))

    monkeypatch.setattr(artifact_object_reads, "_send", object_response)
    session = Session()
    # Share only SDK model-loading caches; each deadline still owns a fresh client.
    monkeypatch.setattr(artifact_object_reads, "Session", lambda: session)

    def deadline_client(timeout):
        assert timeout > 0
        return session.create_client(
            "s3", endpoint_url=env.client.meta.endpoint_url,
            aws_access_key_id="fixture-only", aws_secret_access_key="fixture-only",
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          connect_timeout=timeout, read_timeout=timeout,
                          retries={"total_max_attempts": 1}),
        )

    native_client = deadline_client(0.5)
    env.objects = S3ArtifactObjectStore(
        env.client, bucket=env.objects._bucket, key_prefix=env.objects._key_prefix,
        read_client=artifact_object_reads.bounded_s3_read_client(native_client),
        deadline_client_factory=deadline_client,
    )
    request.addfinalizer(native_client.close)
    request.addfinalizer(env.objects._read_client.close)
    entry = getattr(request, "param", "recovered_snapshot")
    if entry in {"first_create", "empty"}:
        from agent_core.application.session_bootstrap import (
            SessionBootstrapCommand,
            SessionBootstrapService,
        )
        from agent_core.application.workspace_projection import rebuild_workspace
        from agent_core.domain.task_bindings import TaskBindingSnapshot
        from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
        from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction

        if entry == "empty":
            # Only the explicit signed Host fixture changes its exact snapshot.
            # The original fixture Task/run is unrelated and remains intact.
            env.wire.bodies, env.wire.records = (), ()
            env.admission = env.admission.model_copy(update={"max_model_tokens": 200000})
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="native first create",
                user_input="strict native dispatch",
                workspace_root=tmp_path,
                policy_profile="workspace_write",
                host_context=env.host,
                coverage_admission=env.admission,
            )
        )
        env.session = bootstrap.session.session_id
        env.task_binding = TaskBindingSnapshot.model_validate(
            env.task_binding.model_dump() | {"task_id": str(env.session)}
        )
        PostgresTaskAdmissionTransaction(env.dsn, deployment_namespace=NAMESPACE).admit(
            TaskAdmissionRequest(
                events=bootstrap.events,
                session=bootstrap.session,
                workspace=rebuild_workspace(list(bootstrap.events)),
                binding=env.task_binding,
            )
        )
        # A second admitted Task in the same fixture-owned schema has no manifest
        # Event. Its create must traverse the actual native Effect transaction.
        assert not any(
            e.event_type is EventType.COVERAGE_MANIFEST_COMMITTED
            for e in env.events.list_for_session(env.session)
        )
    signed_host = SignedHost(env)
    requests = []

    def response(request):
        requests.append(request)
        if request.url.host == "api.deepseek.com":
            if request.url.path == "/models":
                assert request.headers["Authorization"] == "Bearer fixture-only"
                return httpx.Response(200, json=METADATA)
            if isinstance(env.reply, BaseException):
                raise env.reply
            if getattr(env, "reply_from_request", False):
                payload = json.loads(request.content)
                user = next(message for message in payload["messages"] if message["role"] == "user")
                key = json.loads(user["content"])["key"]
                reply = json.loads(json.dumps(env.reply))
                reply["choices"][0]["message"]["content"] = json.dumps({
                    "key": key, "outcome": "clear", "categories": [], "quotes": [],
                })
                return httpx.Response(200, json=reply)
            return httpx.Response(200, json=env.reply)
        value = signed_host.request(
            request.method,
            str(request.url),
            headers={key.decode(): value.decode() for key, value in request.headers.raw},
            body=json.loads(request.content),
            timeout_seconds=10,
        )
        return httpx.Response(value.status_code, json=value.body)

    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(response))
    monkeypatch.setattr(
        "httpx._client.HTTPTransport", lambda **kwargs: httpx.MockTransport(response)
    )
    monkeypatch.setattr(host_http, "_validate_endpoint", lambda *args, **kwargs: None)
    gateway = HostToolGateway(
        env.host.origin,
        HostWorkloadIdentity("worker", env.host.namespace_id, env.host.host_app_id),
        shared_secret="fixture-secret",
        manifest=env.host_source.host.manifest,
        manifest_binding_policy=(
            "declared" if env.admission.contract.schema_version == 2 else "legacy"
        ),
    )
    monkeypatch.setattr(dispatch, "resolve_pinned_gateway", lambda *args: gateway)
    monkeypatch.setattr(
        "zebra_agent_worker.coverage_recovery.resolve_pinned_gateway", lambda *args: gateway
    )
    monkeypatch.setenv("COVERAGE_FIXTURE_KEY", "fixture-only")
    scope = OpaqueAuthorityScope(
        authority_issuer=env.host.origin, namespace_id=env.host.namespace_id,
    )
    stores = postgres_control_plane_stores(
        env.dsn,
        deployment_namespace=NAMESPACE,
        memory_cursor_signing_key=b"f" * 32,
        artifact_objects=env.objects,
        history_scope=scope,
        continuation_scope=scope,
    )
    models, tools, recovery = compose_recovery(
        stores, stores.worker_projection_transaction, NAMESPACE, stores.artifact_payloads
    )
    replay_reader = PostgresWorkerReplayReader(env.dsn, deployment_namespace=NAMESPACE)
    recorder_factory = WorkerProjectionRecorderFactory(
        stores=stores,
        model_call_indexer=models,
        tool_run_indexer=tools,
        transaction=stores.worker_projection_transaction,
        deployment_namespace=NAMESPACE,
        tail_reader=replay_reader.tail_page,
    )
    claims = SessionClaimService(stores.leases, recovery)
    coordinates = conninfo_to_dict(env.dsn)
    settings_dsn = (
        "postgresql://"
        + quote(coordinates["user"], safe="")
        + ":"
        + quote(coordinates["password"], safe="")
        + "@"
        + coordinates["host"]
        + ":"
        + coordinates["port"]
        + "/"
        + quote(coordinates["dbname"], safe="")
        + "?"
        + urlencode({"options": coordinates["options"]})
    )
    settings = load_settings(
        env={
            "ZEBRA_PROFILE": "cloud",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
            "ZEBRA_DATABASE_URL": settings_dsn,
            "ZEBRA_MODEL_PROVIDER": "deepseek",
            "ZEBRA_MODEL_API_KEY_ENV": "COVERAGE_FIXTURE_KEY",
            "ZEBRA_MODEL_BASE_URL": "https://api.deepseek.com",
            "ZEBRA_MODEL_NAME": "deepseek-v4-pro",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "ZEBRA_DEEPSEEK_REVIEWER_PROFILE": "deepseek-v4-pro-reviewer-v1",
            "ZEBRA_HOST_TOOL_SHARED_SECRET": "fixture-secret",
            # Preserve explicit replacement-per-unit recovery stress cases.
            "ZEBRA_COVERAGE_WORK_UNITS": "1",
        }
    )
    service = SessionExecutionService(
        database_path=tmp_path / "unused.sqlite",
        claim_service=claims,
        resume_service=SessionResumeService(claims),
        settings=settings,
        stores=stores,
        effect_dispatch=stores.effects,
        worker_projection_transaction=stores.worker_projection_transaction,
        deployment_namespace=NAMESPACE,
        recorder_factory=recorder_factory,
        task_binding_loader=lambda _: env.task_binding,
        frozen_manifest_loader=lambda _: env.host_source.host.manifest.to_payload(),
        cloud_artifact_factory=lambda session: CloudToolOutputArtifactCoordinator(
            session, stores.artifact_payloads, env.objects
        ),
        cloud_provider_continuation_factory=lambda session: CloudProviderContinuationCoordinator(
            store=stores.provider_continuations, scope=scope, session_id=session
        ),
        coverage_runtime=CloudCoverageRuntime(
            env.dsn, NAMESPACE, stores.artifact_payloads, env.objects
        ),
    )
    if entry == "recovered_snapshot":
        env.leases.release(env.session, fence=env.fence)
    from agent_core.contracts.broker_envelope import PrincipalScope
    from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
    from agent_core.domain.events import EventActor, SessionEvent

    from tests.agent_storage.test_postgres_command_wakeup import _enable

    _enable(env.dsn)
    env.service, env.stores, env.native_requests = service, stores, requests
    env.signed_host, env.entry = signed_host, entry
    from agent_storage.postgres.host_auth import HostRegistryRecord, PostgresHostAuthorityStore

    PostgresHostAuthorityStore(env.dsn, deployment_namespace=NAMESPACE).upsert_registry(
        HostRegistryRecord(
            host_app_id=env.host.host_app_id,
            namespace_id=env.host.namespace_id,
            issuer=env.task_binding.host_capability.authority_issuer,
            audience="fixture",
            jwks_uri=env.host.origin + "/jwks",
            allowed_origins=(env.host.origin,),
            algorithms=("RS256",),
            policy_version=env.host.policy_version,
        )
    )
    _start_native_capability(env)
    tail = env.events.list_for_session(env.session)[-1].sequence
    command = SessionCommand(
        session_id=env.session,
        kind=SessionCommandKind.RUN,
        expected_revision=tail,
        idempotency_key="native-strict-run",
        payload={"run_id": f"native:{env.session}"},
    )
    from agent_storage.postgres.events import append_event_in_transaction
    from agent_storage.postgres.worker_capability import check_worker_capability_clock

    with env.database.connect() as connection:
        connection.execute(
            "SELECT set_config('zebra.coverage_configuration',%s,true)",
            (env.native_digest,),
        )
        env.native_event = append_event_in_transaction(
            connection,
            NAMESPACE,
            SessionEvent.create(
                session_id=env.session,
                sequence=tail + 1,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                actor=EventActor.USER,
                payload=command.event_payload(),
            ),
        )
        check_worker_capability_clock(
            connection, env.native_capability.lease_for(env.native_consumer)
        )
    # End the actual enqueue process. Fixture-only deletion of its revoked row
    # leaves the durable requirement intact and exercises fresh replacement routing.
    _stop_native_capability(env, remove_revoked=True)
    env.scope = PrincipalScope(
        kind="principal", tenant_id=env.host.namespace_id, workspace_id=env.host.workspace_ref
    )
    try:
        yield env
    finally:
        _stop_native_capability(env)


def complete_execution_discovery(consumer):
    """Fixture-only empty DB response through the actual poll completion path."""
    import asyncio

    async def discover(*args):
        return ()

    if not hasattr(consumer, "_polling"):
        consumer._polling = {"execution": asyncio.Lock()}
        consumer._execution_discovery_generation = 0
        consumer._admission = None
        consumer._batch = 1
        consumer._cursors = {"execution": None}
        consumer._db = discover
    asyncio.run(consumer.poll("execution"))


def _start_native_capability(env):
    """Actual native consumer/control/recovery progress, no injected readiness row."""
    import asyncio
    from time import monotonic

    from agent_runtime.command_wakeup_consumer import CommandWakeupConsumer
    from zebra_agent_worker.command_process_state import (
        CommandRecoverySweep,
        CommandWorkerCapability,
        strict_worker_configuration_digest,
    )
    from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck
    from zebra_agent_worker.worker_loop_service import WorkerLoopService

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    env.native_checker = NativeCoverageRecoveryCheck(env.service._coverage_runtime, env.service)
    capability = CommandWorkerCapability(
        env.dsn,
        NAMESPACE,
        env.service._settings,
        env.service.execute_claimed_session,
        env.native_checker,
    )

    async def quarantine(*args):
        raise AssertionError("fixture's canonical command must not be quarantined")

    consumer = CommandWakeupConsumer(
        env.dsn,
        deployment_namespace=NAMESPACE,
        owner="native-strict-worker",
        execute_claimed=env.service.execute_claimed_session,
        quarantine=quarantine,
        coverage_check=env.native_checker,
        consumer_capability=lambda: capability.lease_for(consumer),
    )

    async def poll():
        await consumer.poll("execution")
        await consumer.poll("control")

    asyncio.run(poll())
    loop = WorkerLoopService(env.stores.sessions, env.service)
    loop.maintenance_once(worker_id="native-strict-worker", batch_size=1, lease_ttl_seconds=30)
    CommandRecoverySweep(env.dsn, NAMESPACE, 16, coverage_check=env.native_checker).tick()
    capability.consumer_tick(consumer, 1, monotonic())
    env.native_digest = strict_worker_configuration_digest(
        env.dsn,
        NAMESPACE,
        env.service._settings,
        env.service.execute_claimed_session,
        env.native_checker,
    )
    assert capability.lease_for(consumer) is not None and env.native_digest is not None
    env.native_capability, env.native_consumer = capability, consumer


def _stop_native_capability(env, *, remove_revoked=False):
    import asyncio

    capability = getattr(env, "native_capability", None)
    if capability is None:
        return
    lease = capability.lease_for(env.native_consumer)
    capability.close()
    asyncio.run(env.native_consumer.close())
    if remove_revoked and lease is not None:
        with env.database.connect() as connection:
            connection.execute(
                "DELETE FROM worker_process_capabilities "
                "WHERE process_id=%s AND revoked_at IS NOT NULL",
                (lease.process_id,),
            )
    env.native_capability = None


def native_handoff(env, *, checker=True):
    from agent_storage.postgres.command_wakeup_handoff import handoff_command

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    # Manual handoffs have no long-lived process polling/heartbeat loop. Each
    # replacement must qualify a real fresh consumer, never reuse its expired token.
    _stop_native_capability(env)
    _start_native_capability(env)

    return handoff_command(
        env.dsn,
        deployment_namespace=NAMESPACE,
        scope=env.scope,
        accepted_event_id=env.native_event.event_id,
        owner_instance_id="native-strict-worker",
        ttl=timedelta(minutes=5),
        consumer_capability=env.native_capability.lease_for(env.native_consumer),
        coverage_check=env.native_checker if checker else None,
    )


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
def test_unregistered_consumer_refuses_before_expensive_proof(native_worker, monkeypatch):
    from unittest.mock import Mock

    from agent_storage.postgres import command_wakeup_handoff
    from agent_storage.postgres.worker_capability import WorkerCapabilityLostError

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    env = native_worker
    before = env.events.list_for_session(env.session)
    prepare = Mock(side_effect=AssertionError("unregistered consumer must not prepare proof"))
    monkeypatch.setattr(command_wakeup_handoff, "prepare_command_handoff", prepare)
    with pytest.raises(WorkerCapabilityLostError, match="qualified consumer"):
        command_wakeup_handoff.handoff_command(
            env.dsn, deployment_namespace=NAMESPACE, scope=env.scope,
            accepted_event_id=env.native_event.event_id, owner_instance_id="unregistered",
            ttl=timedelta(minutes=5), coverage_check=env.native_checker,
        )
    prepare.assert_not_called()
    assert env.events.list_for_session(env.session) == before
    with env.database.connect() as connection:
        assert not connection.execute("SELECT 1 FROM command_handoff_receipts").fetchall()


@pytest.mark.parametrize("native_worker", ["recovered_snapshot", "first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [600, {"v2": True}], indirect=True)
def test_native_worker_dispatch_reuses_governed_snapshot_and_certifies(native_worker):
    from agent_core.domain.events import EventType
    from agent_core.domain.sessions import SessionStatus
    from agent_core.harness.models import HarnessAttemptOutcome
    from agent_storage.postgres.command_wakeup_handoff import HandoffStatus

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    env = native_worker
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.ACCEPTED
    first = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert first.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert first.session.status is SessionStatus.RUNNING
    with env.database.connect() as connection:
        pending = connection.execute(
            "SELECT current_generation,status FROM session_command_pending"
        ).fetchone()
        assert pending == {"current_generation": 1, "status": "pending"}
        approval = connection.execute(
            "SELECT reason,coverage_proof FROM command_recovery_attempts"
        ).fetchone()
        assert approval["reason"] == "coverage_continuation" and approval["coverage_proof"]
    second = native_handoff(env)
    assert second.status is HandoffStatus.ACCEPTED
    assert second.lease.fence != handoff.lease.fence
    result = env.service.execute_claimed_session(second.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.COMPLETED
    events = env.events.list_for_session(env.session)
    starts = [e for e in events if e.event_type is EventType.HARNESS_ATTEMPT_STARTED]
    closes = [e for e in events if e.event_type in {
        EventType.TURN_COMPLETED, EventType.SESSION_COMPLETED,
    }]
    assert len(closes) == 2
    assert all(e.payload["attempt_number"] == starts[-1].payload["attempt_number"] for e in closes)
    assert sum(e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in events) == 1
    assert sum(e.event_type is EventType.COVERAGE_BATCH_ACCEPTED for e in events) == 2
    assert sum(r.url.path == "/chat/completions" for r in env.native_requests) == 1
    assert len(env.signed_host.creates) == (1 if env.entry == "first_create" else 0)
    if env.entry == "first_create":
        with env.database.connect() as connection:
            receipt = connection.execute(
                "SELECT status FROM effect_outbox "
                "WHERE deployment_namespace=%s AND execution_session_id=%s",
                (NAMESPACE, env.session),
            ).fetchall()
        assert receipt and all(r["status"] == "succeeded" for r in receipt)
    assert result.attempt_result.metadata["coverage_report_ref"].startswith("artifact://")
    with env.database.connect() as connection:
        assert (
            connection.execute("SELECT status FROM session_command_pending").fetchone()["status"]
            == "done"
        )


@pytest.mark.parametrize("native_worker", ["empty"], indirect=True)
def test_native_worker_certifies_authorized_empty_snapshot_without_model(native_worker):
    from agent_core.domain.events import EventType
    from agent_core.domain.sessions import SessionStatus
    from agent_storage.postgres.command_wakeup_handoff import HandoffStatus

    env = native_worker
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.ACCEPTED
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.COMPLETED
    events = env.events.list_for_session(env.session)
    assert sum(e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in events) == 1
    assert not any(e.event_type is EventType.COVERAGE_BATCH_ACCEPTED for e in events)
    assert not any(r.url.path == "/chat/completions" for r in env.native_requests)
    assert len(env.signed_host.creates) == 1
    with env.database.connect() as connection:
        run_id = next(
            e.payload["run_id"]
            for e in events
            if e.event_type is EventType.COVERAGE_MANIFEST_COMMITTED
        )
        units = connection.execute(
            "SELECT count(*) AS n FROM coverage_units WHERE run_id=%s", (run_id,)
        ).fetchone()
        assert units["n"] == 0
        assert not connection.execute("SELECT 1 FROM command_recovery_attempts").fetchall()
        assert connection.execute("SELECT status FROM session_command_pending").fetchone() == {
            "status": "done"
        }


def metadata_transport(monkeypatch, *, status=200, body=None):
    native_client = httpx.Client
    clients, requests, transports = [], [], []

    def response(request):
        requests.append(request)
        return httpx.Response(
            status,
            content=json.dumps(METADATA).encode() if body is None else body,
            headers={"Location": "https://untrusted.invalid/models"},
        )

    def transport(**kwargs):
        transports.append(kwargs)
        return httpx.MockTransport(response)

    def client(**kwargs):
        clients.append(kwargs)
        return native_client(**kwargs)

    monkeypatch.setattr(httpx, "HTTPTransport", transport)
    monkeypatch.setattr(httpx, "Client", client)
    return clients, requests, transports


def load(check=lambda: None, **kwargs):
    return load_official_model_policy(
        api_key="fixture-only-not-a-secret",
        deadline=datetime.now(UTC) + timedelta(seconds=30),
        check_authority=check,
        **kwargs,
    )


def test_official_metadata_uses_authenticated_fresh_bounded_transport(monkeypatch):
    clients, requests, transports = metadata_transport(monkeypatch)
    checks = []
    for _ in range(2):
        assert load(lambda: checks.append(True)).original_metadata == json.dumps(METADATA).encode()
    assert len(clients) == len(requests) == len(transports) == 2
    assert all(c["trust_env"] is False and c["follow_redirects"] is False for c in clients)
    assert transports == [{"verify": True, "trust_env": False, "retries": 0}] * 2
    assert all(str(r.url) == MODELS_URL and r.method == "GET" for r in requests)
    assert all(r.headers["Authorization"] == "Bearer fixture-only-not-a-secret" for r in requests)
    assert len(checks) >= 6


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 500])
def test_official_metadata_rejects_status_without_redirect_or_retry(monkeypatch, status):
    _, requests, _ = metadata_transport(monkeypatch, status=status)
    with pytest.raises(CoverageRefusedError):
        load()
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [b"", b"not-json", b"x" * (MAX_METADATA_BYTES + 1)],
    ids=["empty", "invalid", "oversized"],
)
def test_official_metadata_refuses_invalid_or_oversized_original(monkeypatch, body):
    _, requests, _ = metadata_transport(monkeypatch, body=body)
    with pytest.raises(CoverageRefusedError):
        load()
    assert len(requests) == 1


def test_official_metadata_original_deadline_is_checked_after_response(monkeypatch):
    _, requests, _ = metadata_transport(monkeypatch)
    started = datetime.now(UTC)
    clocks = iter([started, started, started + timedelta(seconds=31)])
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        load(now=lambda: next(clocks))
    assert len(requests) == 1


def test_official_metadata_authority_failure_prevents_transport(monkeypatch):
    _, requests, transports = metadata_transport(monkeypatch)

    def revoked():
        raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        load(revoked)
    assert requests == transports == []


def test_native_composition_refusal_is_sanitized_for_fenced_worker_cleanup(monkeypatch):
    from types import SimpleNamespace

    from zebra_agent_worker.coverage_composition import CloudCoverageRuntime
    from zebra_agent_worker.execution_finalization import WorkerExecutionError

    class Recorder:
        session = SimpleNamespace()

    runtime = CloudCoverageRuntime("unused", "fixture", None, None)
    service = SimpleNamespace(_task_binding_loader=None)
    inputs = SimpleNamespace(
        task=None, claimed=SimpleNamespace(lease=SimpleNamespace(session_id=1))
    )
    # Invoke the actual dispatch's first boundary, not a replacement dispatcher.
    with pytest.raises(
        WorkerExecutionError, match="^strict coverage refused: coverage_unsupported$"
    ) as error:
        runtime.execute(service, inputs, Recorder(), lambda: None)
    assert error.value.__cause__ is None
