"""Pure HTTP/orchestration checks, explicitly not native transaction evidence."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from agent_core.contracts.session_commands import validate_accepted_session_command
from agent_core.domain.events import EventType
from agent_core.ports.task_admission_transaction import TaskAdmissionReceipt
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from agent_storage import PostgresCloudArtifactPayloadStore, S3ArtifactObjectStore
from agent_storage.artifact_payload_reads import CloudArtifactPayloadReader
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.coverage_http_admission import (
    CoverageHttpAdmission,
    compose_coverage_http_admission,
)
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_config import load_settings

from tests.agent_core.test_coverage_task_admission import admission, host
from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn  # noqa: F401
from tests.worker.test_coverage_dispatch import native_worker  # noqa: F401


def composed_app():
    settings = load_settings(env={})
    settings = replace(
        settings,
        profile="cloud",
        database_url="unused-dsn",
        model=replace(settings.model, reviewer_profile="review-profile"),
    )
    stores = SimpleNamespace(deployment_namespace="test-deployment", artifact_payloads=None)
    return ZebraAgentApi(
        database_path=None,
        settings=settings,
        _stores=stores,
        coverage_http_admission=CoverageHttpAdmission("unused-dsn", "test-deployment", "a" * 64),
    )


def grant():
    context = host()
    return VerifiedHostGrant(
        context, context.grant_id, JwtAlgorithm.RS256, "https://issuer.example", "test-principal"
    )


def payload():
    return {
        "prompt": "review",
        "execute": True,
        "coverage_admission": admission().model_dump(mode="json"),
    }


def test_structural_parser_retains_typed_coverage_but_default_schedule_stays_closed():
    raw = payload()
    parsed = parse_create_session_payload(raw, structural_only=True)
    assert parsed["coverage_admission"] == admission()
    assert parse_create_session_payload(raw).status_code == 503
    assert (
        parse_create_session_payload(
            raw | {"coverage_admission": None}, structural_only=True
        ).status_code
        == 400
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"attachments": [{"filename": "a.txt", "text": "x"}]},
        {"history_session_ids": ["11111111-1111-1111-1111-111111111111"]},
        {"definition_id": "11111111-1111-1111-1111-111111111111"},
        {"skill_components": ["test-skill"]},
    ],
)
def test_unsupported_options_never_reach_readiness_or_host_effects(monkeypatch, extra):
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported input reached composition")

    monkeypatch.setattr(CoverageHttpAdmission, "preflight", forbidden)
    response = composed_app().create_session(payload() | extra, idempotency_key="key")
    assert response.status_code in (400, 503)


def test_missing_verified_host_or_non_atomic_create_is_refused_before_readiness(monkeypatch):
    monkeypatch.setattr(CoverageHttpAdmission, "preflight", lambda self: pytest.fail("late gate"))
    app = composed_app()
    assert app.create_session(payload()).status_code == 403
    assert app.create_session(payload() | {"execute": False}).status_code == 400


def test_native_refusal_precedes_manifest_and_is_sanitized(monkeypatch):
    from zebra_agent_api import session_binding

    def missing(self):
        raise RuntimeError("must-not-leak-provider-or-dsn")

    monkeypatch.setattr(CoverageHttpAdmission, "preflight", missing)
    monkeypatch.setattr(
        session_binding,
        "_frozen_manifest_digest",
        lambda *args: pytest.fail("Host manifest reached"),
    )
    verified = grant()
    response = composed_app().create_session(
        payload(), host_context=verified.context, verified_host_grant=verified
    )
    assert response.status_code == 503
    assert response.body == {"status": "coverage_unsupported", "reason": "strict_worker_not_ready"}


@pytest.mark.parametrize("validation_mode", [None, "eager", "final_certification"])
def test_queued_receipt_and_canonical_run_are_built_before_single_atomic_admission(
    monkeypatch, validation_mode
):
    from agent_storage.postgres import command_coverage_admission
    from zebra_agent_api import session_binding

    raw = payload()
    expected = dict(raw["coverage_admission"])
    assert "validation_mode" not in expected
    if validation_mode is not None:
        raw["coverage_admission"]["validation_mode"] = validation_mode
    if validation_mode == "final_certification":
        expected["validation_mode"] = validation_mode
    captured = []
    monkeypatch.setattr(CoverageHttpAdmission, "preflight", lambda self: None)
    monkeypatch.setattr(session_binding, "_frozen_manifest_digest", lambda *args: "b" * 64)

    def admit(database_dsn, namespace, request, digest):
        request.validate()
        captured.append(request)
        assert digest == "a" * 64 and namespace == "test-deployment"
        assert len(request.events) == 4
        prepared, run = request.events[2:]
        assert prepared.event_type is EventType.TASK_PREPARED
        assert prepared.payload["coverage_admission"] == expected
        assert run.event_type is EventType.SESSION_COMMAND_ACCEPTED
        accepted = validate_accepted_session_command(
            run.payload,
            session_id=run.session_id,
            idempotency_key=run.idempotency_key,
        )
        assert accepted.expected_revision == request.session.current_sequence == 2
        assert request.workspace.current_sequence == 2
        assert request.idempotency.response_body["status"] == "queued"
        assert request.idempotency.response_body["idempotency_key"] == "public-key"
        assert request.idempotency.response_body["command"]["event_sequence"] == run.sequence == 3
        return TaskAdmissionReceipt(
            request.session.session_id,
            request.session.session_id,
            4,
            request.binding.binding_digest,
        )

    monkeypatch.setattr(command_coverage_admission, "admit_coverage_task", admit)
    verified = grant()
    response = composed_app().create_session(
        raw,
        idempotency_key="public-key",
        host_context=verified.context,
        verified_host_grant=verified,
    )
    assert response.status_code == 201 and len(captured) == 1
    assert response.body == captured[0].idempotency.response_body


def test_api_descriptor_comes_from_exact_composed_object_store():
    from agent_storage.worker_capability_configuration import worker_capability_configuration_digest

    app = composed_app()
    metadata = PostgresCloudArtifactPayloadStore("unused-dsn", deployment_namespace="native")
    objects = S3ArtifactObjectStore(
        SimpleNamespace(meta=SimpleNamespace(endpoint_url="https://fixture-s3.example")),
        bucket="actual-bucket",
        key_prefix="actual-prefix",
        deadline_client_factory=lambda timeout: None,
    )
    reader = CloudArtifactPayloadReader(metadata, objects, deployment_namespace="native")
    stores = SimpleNamespace(
        artifact_payload_reader=reader, artifact_payloads=metadata, deployment_namespace="native"
    )
    composed = compose_coverage_http_admission(app.settings, stores)
    assert composed.configuration_digest == worker_capability_configuration_digest(
        app.settings,
        namespace="native",
        bucket=objects._bucket,
        key_prefix=objects._key_prefix,
        object_endpoint=objects._client.meta.endpoint_url,
    )
    assert compose_coverage_http_admission(app.settings, SimpleNamespace(ready=True)) is None
    assert (
        compose_coverage_http_admission(replace(app.settings, database_url="other"), stores) is None
    )
    objects._deadline_client_factory = None
    assert compose_coverage_http_admission(app.settings, stores) is None


def native_http_app(env):
    """Actual API composition and frozen fixture Host manifest, no readiness injection."""
    from agent_core.domain.host_connectors import HostConnectorBinding, HostConnectorProfileVersion
    from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
    from agent_storage.postgres.host_manifest_freeze import store_frozen_manifest
    from zebra_agent_api.factory import create_app

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE
    from tests.worker.test_coverage_dispatch import _start_native_capability

    _start_native_capability(env)
    registry = PostgresHostConnectorRegistry(env.dsn, deployment_namespace=NAMESPACE)
    registry.publish_profile(
        HostConnectorProfileVersion(
            host_app_id=env.host.host_app_id,
            connector_id="strict-http",
            profile_revision=1,
            base_uri="https://trench.example",
            manifest_path="/manifest",
            invoke_path_template="/invoke",
            supported_protocol_versions=("1.0",),
            workload_identity_ref="fixture-worker",
            credential_ref="fixture-credential",
        )
    )
    registry.bind(
        HostConnectorBinding(
            host_app_id=env.host.host_app_id,
            namespace_id=env.host.namespace_id,
            connector_id="strict-http",
            profile_revision=1,
            binding_revision=1,
        )
    )
    manifest = env.host_source.host.manifest
    store_frozen_manifest(
        env.dsn,
        deployment_namespace=NAMESPACE,
        manifest_digest=manifest.digest,
        connector_id="strict-http",
        profile_revision=1,
        manifest_payload=manifest.to_payload(),
    )
    api = create_app(
        settings=replace(env.service._settings, database_url=env.dsn), stores=env.stores
    )
    assert api.coverage_http_admission.configuration_digest == env.native_digest
    verified = VerifiedHostGrant(
        env.host,
        env.host.grant_id,
        JwtAlgorithm.RS256,
        env.task_binding.host_capability.authority_issuer,
        "fixture-principal",
    )
    return (
        api,
        verified,
        {
            "prompt": "strict HTTP native",
            "execute": True,
            "coverage_admission": env.admission.model_dump(mode="json"),
        },
    )


def admission_counts(env):
    tables = (
        "agent_tasks",
        "task_binding_snapshots",
        "session_events",
        "control_plane_idempotency_records",
        "session_command_pending",
        "broker_outbox",
        "command_coverage_requirements",
    )
    with env.database.connect() as connection:
        return tuple(
            connection.execute("SELECT count(*) AS n FROM " + table).fetchone()["n"]
            for table in tables
        )


@pytest.mark.parametrize("native_worker", ["empty"], indirect=True)
def test_native_http_atomic_receipt_replay_and_durable_requirement(native_worker):  # noqa: F811
    from uuid import UUID

    env = native_worker
    api, verified, raw = native_http_app(env)
    response = api.create_session(
        raw, idempotency_key="atomic-native", host_context=env.host, verified_host_grant=verified
    )
    assert response.status_code == 201 and response.body["status"] == "queued"
    before = admission_counts(env)
    replay = api.create_session(
        raw, idempotency_key="atomic-native", host_context=env.host, verified_host_grant=verified
    )
    assert replay == response and admission_counts(env) == before
    with env.database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM command_coverage_requirements WHERE session_id=%s",
            (UUID(response.body["session_id"]),),
        ).fetchone()
        assert row["configuration_digest"] == env.native_digest
        assert row["contract"].endswith("bounded-multipart:same-session:validation-mode:v3")
        assert "process_id" not in row
    conflict = api.create_session(
        raw | {"prompt": "different"},
        idempotency_key="atomic-native",
        host_context=env.host,
        verified_host_grant=verified,
    )
    assert conflict.status_code == 409 and admission_counts(env) == before


@pytest.mark.parametrize("native_worker", ["empty"], indirect=True)
@pytest.mark.parametrize("refusal", ["revoked", "config", "rollout", "epoch", "schema", "endpoint"])
def test_native_http_refusal_creates_no_admission_state(native_worker, refusal):  # noqa: F811
    from agent_storage import rotate_control_plane_epoch

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    env = native_worker
    api, verified, raw = native_http_app(env)
    if refusal == "endpoint":
        env.client.meta.endpoint_url = "https://different-actual-s3.example"
        api = replace(
            api, coverage_http_admission=compose_coverage_http_admission(api.settings, api.stores)
        )
    with env.database.connect() as connection:
        if refusal == "revoked":
            connection.execute(
                "UPDATE worker_process_capabilities SET revoked_at=clock_timestamp()"
            )
        elif refusal == "config":
            connection.execute(
                "UPDATE worker_process_capabilities SET configuration_digest=%s", ("0" * 64,)
            )
        elif refusal == "rollout":
            connection.execute("UPDATE command_wakeup_rollouts SET admission_enabled=FALSE")
        elif refusal == "schema":
            connection.execute("UPDATE worker_process_capabilities SET schema_oid=0")
    if refusal == "epoch":
        rotate_control_plane_epoch(env.dsn, deployment_namespace=NAMESPACE)
    before = admission_counts(env)
    response = api.create_session(
        raw, idempotency_key="refuse-native", host_context=env.host, verified_host_grant=verified
    )
    assert response.status_code == 503 and admission_counts(env) == before


@pytest.mark.parametrize("native_worker", ["empty"], indirect=True)
@pytest.mark.parametrize("final_gate", ["python", "deferred", "runtime"])
def test_native_final_clock_expiry_rolls_back_all_admission_rows(
    native_worker,  # noqa: F811
    monkeypatch,
    final_gate,  # noqa: F811
):
    from agent_storage.postgres import command_coverage_admission
    from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction

    env = native_worker
    api, verified, raw = native_http_app(env)
    cap = env.native_capability
    if final_gate == "runtime":
        raw["coverage_admission"]["max_runtime_seconds"] = 1
    else:
        cap._lease = cap._store.heartbeat(
            cap.lease_for(env.native_consumer),
            configuration_digest=env.native_digest,
            ttl_seconds=1,
        )
    original = PostgresTaskAdmissionTransaction.admit_in_transaction
    reached = []

    def delayed(self, connection, namespace, request):
        result = original(self, connection, namespace, request)
        assert (
            connection.execute(
                "SELECT 1 FROM session_command_pending WHERE session_id=%s",
                (request.session.session_id,),
            ).fetchone()
            is not None
        )
        reached.append(True)
        connection.execute("SELECT pg_sleep(1.1)")
        return result

    monkeypatch.setattr(PostgresTaskAdmissionTransaction, "admit_in_transaction", delayed)
    if final_gate in {"deferred", "runtime"}:
        # Native deferred trigger proof independent of Python's final clock.
        monkeypatch.setattr(
            command_coverage_admission, "check_worker_capability_clock", lambda *a: None
        )
    before = admission_counts(env)
    response = api.create_session(
        raw, idempotency_key="delayed-native", host_context=env.host, verified_host_grant=verified
    )
    assert reached == [True] and response.status_code == 503
    assert admission_counts(env) == before


@pytest.mark.parametrize("native_worker", ["empty"], indirect=True)
@pytest.mark.parametrize("expiry", ["during-pin", "after-pin"])
def test_native_consumer_pin_refuses_runtime_expiry_during_capability_wait(
    native_worker,  # noqa: F811
    monkeypatch,
    expiry,
):
    from uuid import UUID

    from agent_storage.postgres import command_coverage_admission as module
    from agent_storage.postgres.worker_capability import WorkerCapabilityLostError

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    env = native_worker
    api, verified, raw = native_http_app(env)
    raw["coverage_admission"]["max_runtime_seconds"] = 2
    response = api.create_session(
        raw,
        idempotency_key="pin-runtime",
        host_context=env.host,
        verified_host_grant=verified,
    )
    assert response.status_code == 201
    original = module.pin_worker_capability
    reached = []

    def delayed(connection, *args, **kwargs):
        lease = original(connection, *args, **kwargs)
        reached.append(True)
        connection.execute("SET LOCAL statement_timeout = '5s'")
        connection.execute("SELECT pg_sleep(2.1)")
        return lease

    if expiry == "during-pin":
        monkeypatch.setattr(module, "pin_worker_capability", delayed)
    before = admission_counts(env)
    with pytest.raises(WorkerCapabilityLostError):
        with env.database.connect() as connection:
            # Only this expiry control permits a bounded sleep past the Task deadline.
            connection.execute("SET LOCAL statement_timeout = '5s'")
            command = connection.execute(
                "SELECT accepted_event_id FROM command_coverage_requirements WHERE session_id=%s",
                (UUID(response.body["session_id"]),),
            ).fetchone()
            pinned = module.pin_command_consumer(
                connection,
                NAMESPACE,
                command["accepted_event_id"],
                env.native_capability.lease_for(env.native_consumer),
                lock_task_authority=True,
            )
            if expiry == "after-pin":
                assert (
                    pinned.expires_at
                    < env.native_capability.lease_for(env.native_consumer).expires_at
                )
                connection.execute("SET LOCAL statement_timeout = '5s'")
                connection.execute("SELECT pg_sleep(2.1)")
                reached.append(True)
                module.check_worker_capability_clock(connection, pinned)
    assert reached == [True] and admission_counts(env) == before


@pytest.mark.parametrize("native_worker", ["empty"], indirect=True)
def test_native_pinned_task_authority_blocks_actual_renewal_lock(native_worker):  # noqa: F811
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.command_coverage_admission import pin_command_consumer
    from agent_storage.postgres.task_index_transactions import _lock_task
    from psycopg.errors import QueryCanceled

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE
    from tests.worker.test_coverage_dispatch import _start_native_capability

    env = native_worker
    _start_native_capability(env)
    with env.database.connect() as pinned:
        assert (
            pin_command_consumer(
                pinned,
                NAMESPACE,
                env.native_event.event_id,
                env.native_capability.lease_for(env.native_consumer),
                lock_task_authority=True,
            )
            is not None
        )
        with pytest.raises(QueryCanceled):
            with env.database.connect() as renewal:
                renewal.execute("SET LOCAL statement_timeout = '100ms'")
                _lock_task(renewal, NAMESPACE, TaskId(env.session))
    with env.database.connect() as renewal:
        renewal.execute("SET LOCAL statement_timeout = '100ms'")
        _lock_task(renewal, NAMESPACE, TaskId(env.session))
