"""Actual scratch PG; S3, signed Host transport and provider metadata are fixtures.

Metadata parsing is not authenticated origin proof. No live model generation or
Worker activation occurs. Only the imported fixture's unique schema is dropped.
"""

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from agent_core.application.coverage_semantic import semantic_check
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_validation import expected_units, manifest_digest
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_integrations.coverage_model_invocation import CoverageModelInvocation
from agent_integrations.coverage_model_policy import REVIEWER_PROFILE, OfficialDeepSeekPolicy
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    PostgresLeaseStore,
    S3ArtifactObjectStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts
from zebra_agent_worker.coverage_bootstrap import bootstrap_cloud_coverage

from tests.agent_integrations.test_coverage_snapshot import AUTHORITY, CONTRACT
from tests.agent_integrations.test_coverage_snapshot_preparation import setup_source
from tests.agent_storage.test_command_wakeup import _binding
from tests.agent_storage.test_postgres_command_wakeup import (  # noqa: F401
    NAMESPACE,
    dsn,
    postgres_dsn,
)
from tests.agent_storage.test_s3_artifact_objects import _FakeS3Client

CAPACITY = 1048576
METADATA = {
    "object": "list",
    "data": [
        {
            "id": "deepseek-v4-pro",
            "object": "model",
            "owned_by": "deepseek",
            "context_window": CAPACITY,
            "max_output_tokens": 393216,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "effort": {"supported_levels": ["low", "high", "max"], "default_level": "high"},
        }
    ],
}


def check_authority(env):
    """Read committed Task/Host/STOP and native epoch/lease at every boundary.

    No Task/run/advisory locks: the publisher calls this inside its transaction.
    Its native transaction remains responsible for atomic mutation fencing.
    """
    env.history = env.events.list_for_session(env.session)
    env.revision = env.history[-1].sequence
    env.host_source.host.authority_check(env.host)
    # Trusted test seam representing the external signed Host revocation feed.
    if env.wire.revoked:
        raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)
    with env.database.connect() as connection:
        assert_current_lease_fence(connection, NAMESPACE, env.session, env.fence)
        row = connection.execute(
            """SELECT t.active_segment_id,b.snapshot_json,b.binding_digest,s.current_version
               FROM agent_tasks t JOIN session_streams s ON
                 s.deployment_namespace=t.deployment_namespace AND s.session_id=%s
               JOIN LATERAL (SELECT snapshot_json,binding_digest FROM task_binding_snapshots
                 WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id
                 ORDER BY binding_revision DESC LIMIT 1) b ON TRUE
               WHERE t.deployment_namespace=%s AND t.task_id=%s""",
            (env.session, NAMESPACE, env.session),
        ).fetchone()
        bound = TaskBindingSnapshot.model_validate(row["snapshot_json"])
        if (
            row["active_segment_id"] != env.session
            or row["current_version"] != env.revision
            or bound != env.task_binding
            or row["binding_digest"] != bound.binding_digest
            or bound.host_capability.host_context != env.host
            or bound.host_capability.grant_digest != host_context_digest(env.host)
            or bound.host_capability.grant_expires_at <= datetime.now(UTC)
        ):
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)
    prepared = [e for e in env.history if e.event_type == EventType.TASK_PREPARED]
    if not prepared or any(
        e.payload["coverage_admission"] != env.admission.model_dump(mode="json")
        or e.payload["host_context"] != env.host.model_dump(mode="json")
        for e in prepared
    ):
        raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)
    if any(
        e.event_type
        in {EventType.SESSION_CANCELLED, EventType.SESSION_FAILED, EventType.SESSION_COMPLETED}
        or (
            e.event_type == EventType.SESSION_COMMAND_ACCEPTED
            and e.payload.get("kind") in {"stop", "cancel"}
        )
        for e in env.history
    ):
        raise CoverageRefusedError(CoverageRefusalReason.CANCELLED)


def authority(env):
    check_authority(env)
    return WorkerMutationAuthority(
        deployment_namespace=NAMESPACE,
        session_id=env.session,
        expected_stream_revision=env.revision,
        lease_fence=env.fence,
    )


def compose(env, *, replacement=False, proof=None):
    if replacement:
        env.leases.release(env.session, fence=env.fence)
        env.fence = env.leases.acquire(
            env.session, owner_instance_id="replacement", ttl=timedelta(minutes=5)
        ).fence
    metadata = PostgresCloudArtifactPayloadStore(env.dsn, deployment_namespace=NAMESPACE)
    publisher = PostgresCoverageArtifactPublisher(
        env.dsn,
        deployment_namespace=NAMESPACE,
        metadata=metadata,
        objects=env.objects,
    )
    env.cloud = CloudCoverageArtifacts(
        binding=env.binding,
        deployment_namespace=NAMESPACE,
        metadata=metadata,
        objects=env.objects,
        publisher=publisher,
        authority=lambda: authority(env),
        check_authority=lambda: check_authority(env),
        sync_events=lambda: check_authority(env),
    )
    env.artifacts = CoverageArtifacts(env.cloud, env.session, nullcontext())
    env.store = PostgresCoverageStore(
        env.dsn,
        deployment_namespace=NAMESPACE,
        artifacts=env.cloud,
        supported_model_profiles=(REVIEWER_PROFILE,),
    )
    env.policy = env.store.initialize_model_budget(env.binding, fence=env.fence)
    return CoverageModelInvocation(
        binding=env.binding,
        artifacts=env.artifacts,
        budget_store=env.store,
        original_policy=env.policy,
        fresh_fence=lambda: authority(env).lease_fence,
        check_authority=lambda: check_authority(env),
        gateway_factory=env.factory,
        trusted_proof=proof or env.proof,
        allow_mock_transport=True,
    )


@pytest.fixture
def model_cloud(dsn, request):  # noqa: F811
    from agent_core.domain.coverage_execution import CoverageExecutionBudget
    from agent_core.domain.coverage_task_admission import CoverageTaskAdmission

    now = datetime.now(UTC)
    runtime = getattr(request, "param", 600)
    validation_mode = "eager"
    if isinstance(runtime, dict):
        validation_mode = runtime["validation_mode"]
        runtime = runtime.get("runtime", 600)
    definition = semantic_check(REVIEWER_PROFILE)
    contract = CONTRACT.model_copy(update={"checks": (definition.contract_check,)})
    host = AUTHORITY.model_copy(
        update={
            "expires_at": now + timedelta(hours=1),
            "limits": AUTHORITY.limits.model_copy(
                update={
                    "max_model_tokens": CAPACITY * 2,
                    "max_runtime_seconds": runtime,
                }
            ),
        }
    )
    admission = CoverageTaskAdmission(
        contract=contract,
        history_ref="history",
        model_profile=REVIEWER_PROFILE,
        validation_mode=validation_mode,
        execution_budget=CoverageExecutionBudget(max_attempts=100, max_input_bytes=1000),
        max_model_calls=2,
        max_model_tokens=CAPACITY * 2,
        max_runtime_seconds=runtime,
    )
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="scratch MODEL acceptance",
            user_input="strict fixture",
            workspace_root="/tmp/coverage-model-cloud",
            host_context=host,
            coverage_admission=admission,
            created_at=now,
        )
    )
    session = bootstrap.session.session_id
    text = 'source🙂 停产。\n"quoted"'
    source, wire, _ = setup_source(
        (text.encode(),),
        session_id=session,
        authority=host,
        now=lambda: datetime.now(UTC),
    )

    def mutate(name, value):
        if name in {"create", "get"}:
            value["snapshot"].update(
                contract_digest=contract.digest,
                manifest_digest=manifest_digest(contract, wire.records),
                as_of=now.isoformat(),
                expires_at=(now + timedelta(hours=1)).isoformat(),
            )
            value["sealed_at"] = now.isoformat()
        return value

    wire.mutate = mutate
    data = _binding(
        str(session), tenant=host.namespace_id, workspace=host.workspace_ref
    ).model_dump()
    data["host_capability"].update(
        host_context=host,
        grant_digest=host_context_digest(host),
        grant_expires_at=host.expires_at,
        manifest_digest=source.host.manifest.digest,
    )
    task_binding = TaskBindingSnapshot.model_validate(data)
    PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
        TaskAdmissionRequest(
            events=bootstrap.events,
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
            binding=task_binding,
        )
    )
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
    leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
    env = SimpleNamespace(
        dsn=dsn,
        database=PostgresDatabase(dsn, deployment_namespace=NAMESPACE),
        host=host,
        admission=admission,
        task_binding=task_binding,
        session=session,
        source=source,
        host_source=source,
        wire=wire,
        leases=leases,
        definition=definition,
        fence=leases.acquire(session, owner_instance_id="original", ttl=timedelta(minutes=5)).fence,
        events=PostgresEventStore(dsn, deployment_namespace=NAMESPACE),
        client=_FakeS3Client(),
        clients=[],
        requests=[],
        http_boundary=None,
        now=now,
        proof=OfficialDeepSeekPolicy(json.dumps(METADATA).encode()),
    )
    env.objects = S3ArtifactObjectStore(
        env.client,
        bucket="model-cloud-fixture",
        deadline_client_factory=lambda timeout: env.client,
    )
    result = bootstrap_cloud_coverage(
        dsn=dsn,
        deployment_namespace=NAMESPACE,
        metadata=PostgresCloudArtifactPayloadStore(dsn, deployment_namespace=NAMESPACE),
        objects=env.objects,
        source=source,
        host_authority=host,
        admission=admission,
        task_id=TaskId(session),
        session_id=session,
        run_id=str(session),
        fence=env.fence,
        authority=lambda: authority(env),
        check_authority=lambda: check_authority(env),
        sync_events=lambda: check_authority(env),
    )
    env.binding = result.binding
    env.key = next(k for k in expected_units(contract, result.records) if k.kind == "part")
    env.record, env.source = result.records[0], text
    # Keep the real Host source separately; invocation message helper expects text.
    env.host_source = source
    env.reply = {
        "model": "deepseek-v4-pro",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "reasoning_content": "私有完整推理🙂",
                    "content": json.dumps(
                        {
                            "key": env.key.model_dump(mode="json"),
                            "outcome": "clear",
                            "categories": [],
                            "quotes": [],
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "prompt_cache_hit_tokens": 4,
            "prompt_cache_miss_tokens": 6,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    }

    def handle(request):
        env.requests.append(request)
        if isinstance(env.reply, Exception):
            raise env.reply
        if env.http_boundary is not None:
            env.http_boundary()
        return httpx.Response(200, json=env.reply)

    def factory():
        client = httpx.Client(
            transport=httpx.MockTransport(handle), trust_env=False, follow_redirects=False
        )
        env.clients.append(client)
        return OpenAICompatibleModelGateway(
            provider_name="deepseek",
            base_url="https://api.deepseek.com",
            api_key="fixture-only",
            model_name="deepseek-v4-pro",
            max_retries=0,
            client=client,
        )

    env.factory = factory
    try:
        yield env
    finally:
        for client in env.clients:
            client.close()
