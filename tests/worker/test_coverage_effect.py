"""Real PG + real Cloud Artifact lifecycle + signed fake Host transport."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import psycopg
import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.effect_dispatch import EffectDispatchStateError
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.tools import ToolCall
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_integrations.host_tools.contracts import HostToolTransportResponse, HostWorkloadIdentity
from agent_integrations.host_tools.gateway import HostToolGateway
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.outbox import PostgresEffectDispatchStore
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from zebra_agent_worker.cloud_effect_payloads import CloudEffectPayloadCoordinator
from zebra_agent_worker.coverage_effect import CloudCoverageEffectInvoke
from zebra_agent_worker.coverage_effect_validation import CREATE, create_arguments, create_call_id
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator

from tests.agent_storage.test_postgres_effect_dispatch import _request
from tests.worker import test_coverage_bootstrap as bootstrap_tests

dsn = bootstrap_tests.dsn
postgres_dsn = bootstrap_tests.postgres_dsn
cloud = bootstrap_tests.cloud
NAMESPACE = bootstrap_tests.NAMESPACE


class SignedHost:
    def __init__(self, env):
        self.env = env
        self.creates = []
        self.unknown = False

    def request(self, method, url, *, headers, body, timeout_seconds):
        context = self.env.host
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        message = (
            f"{method}\n{urlsplit(url).path}\n{context.grant_id}\n{context.workspace_ref}\n"
            f"{context.host_app_id}\n{context.namespace_id}\n{encoded}"
        ).encode()
        assert hmac.compare_digest(
            headers["X-Zebra-Host-Auth"],
            hmac.new(b"fixture-secret", message, hashlib.sha256).hexdigest(),
        )
        response = self.env.wire.request(
            method, url, headers=headers, body=body, timeout_seconds=timeout_seconds
        )
        if body["toolName"] != CREATE:
            return response
        self.creates.append(body)
        return HostToolTransportResponse(
            200,
            {
                **response.body,
                "effectStatus": "unknown" if self.unknown else "succeeded",
                "providerOperationId": "create-" + str(len(self.creates)),
                "businessRevision": "revision-1",
            },
        )


class Policy:
    decision = PolicyDecisionType.ALLOW

    def evaluate_tool_call(self, call):
        assert call.name == CREATE
        return PolicyDecision(decision=self.decision, reason="fixture", policy_profile="fixture")


@pytest.fixture
def effect(cloud):
    env = cloud
    env.transport = SignedHost(env)
    env.gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("worker", "ns", "trench"),
        shared_secret="fixture-secret",
        transport=env.transport,
        manifest=env.source.host.manifest,
    )
    env.dispatch = PostgresEffectDispatchStore(env.dsn, deployment_namespace=NAMESPACE)
    env.artifacts = CloudToolOutputArtifactCoordinator(env.session, env.metadata, env.objects)
    env.payloads = CloudEffectPayloadCoordinator(env.session, env.artifacts, env.dispatch)
    env.policy = Policy()
    env.revoked = False

    def check():
        if env.revoked:
            raise ValueError("external authority revoked")

    def next_event(kind, actor, payload):
        return SessionEvent.create(
            session_id=env.session,
            sequence=env.revision + 1,
            event_type=kind,
            actor=actor,
            payload=payload,
        )

    def accept(event):
        assert env.events.list_for_session(env.session)[-1] == event
        env.revision = event.sequence

    env.callback_kwargs = dict(
        payloads=env.payloads,
        gateway=env.gateway,
        admission=env.admission,
        binding=env.task_binding,
        context=env.host,
        fence=env.fence,
        authority=env.kwargs["authority"],
        policy=env.policy,
        check_authority=check,
        next_event=next_event,
        accept_event=accept,
    )
    env.callback = CloudCoverageEffectInvoke(**env.callback_kwargs)
    return env


def invocation(env, key=" opaque key "):
    args = create_arguments(env.admission)
    resource = HostResourceRef(type="trench.history", id=env.admission.history_ref)
    call = ToolCall(
        tool_call_id=create_call_id(key, env.host, env.gateway.manifest, args, resource),
        name=CREATE,
        arguments=args,
        created_at=datetime.now(UTC),
    )
    kwargs = dict(
        context=env.host,
        idempotency_key=key,
        required_resource=resource,
        manifest=env.gateway.manifest,
    )
    return call, kwargs


def queue(env):
    with psycopg.connect(env.dsn, row_factory=dict_row) as connection:
        return connection.execute("SELECT * FROM effect_outbox ORDER BY dispatch_id").fetchall()


def persisted(env):
    with psycopg.connect(env.dsn, row_factory=dict_row) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("effect_outbox", "session_events", "artifact_payload_metadata")
        }


def test_signed_source_mixed_queue_replacement_replays_original_once(effect):
    env = effect
    sibling = env.dispatch.schedule(
        _request(
            execution_session_id=env.session, root_session_id=env.session, sequence=env.revision + 1
        ),
        fence=env.fence,
    )
    env.revision += 1
    before = queue(env)
    source = HostCoverageSnapshotSource(
        session_id=env.session,
        authority=env.host,
        history_ref=env.admission.history_ref,
        manifest=env.gateway.manifest,
        invoke=env.gateway.invoke,
        admitted_effect_invoke=env.callback,
    )
    first = source.create(
        env.admission.contract, authority=env.host, idempotency_key=" opaque key "
    )
    call, kwargs = invocation(env)
    original = env.callback(call, **kwargs)
    assert env.transport.creates[0]["idempotencyKey"] == " opaque key "
    assert len(env.transport.creates) == 1
    assert next(row for row in queue(env) if row["dispatch_id"] == sibling.dispatch_id) == before[0]
    env.leases.release(env.session, fence=env.fence)
    old_callback = env.callback
    env.fence = env.leases.acquire(
        env.session, owner_instance_id="replacement", ttl=timedelta(minutes=5)
    ).fence
    env.callback_kwargs["fence"] = env.fence
    env.callback = CloudCoverageEffectInvoke(**env.callback_kwargs)
    source.host.effect = env.callback
    replay = source.create(
        env.admission.contract, authority=env.host, idempotency_key=" opaque key "
    )
    assert replay.descriptor == first.descriptor
    assert env.callback(call, **kwargs) == original
    assert len(env.transport.creates) == 1
    before = queue(env)
    with pytest.raises(ValueError):
        old_callback(call, **kwargs)
    assert queue(env) == before
    changed_call, changed_kwargs = invocation(env, "opaque key")
    assert changed_call.tool_call_id != call.tool_call_id
    env.callback(changed_call, **changed_kwargs)
    assert len(env.transport.creates) == 2


@pytest.mark.parametrize(
    "problem",
    ["key", "id", "args", "context", "resource", "manifest", "raw", "policy", "revoked", "stale"],
)
def test_wrong_identity_denies_before_schedule_or_transport(effect, problem):
    env = effect
    call, kwargs = invocation(env)
    if problem == "key":
        kwargs["idempotency_key"] = "other"
    elif problem == "id":
        call = call.model_copy(update={"tool_call_id": new_tool_call_id()})
    elif problem == "args":
        call = call.model_copy(update={"arguments": {**call.arguments, "extra": True}})
    elif problem == "context":
        kwargs["context"] = env.host.model_copy(update={"grant_id": "foreign"})
    elif problem == "resource":
        kwargs["required_resource"] = HostResourceRef(type="trench.history", id="foreign")
    elif problem == "manifest":
        kwargs["manifest"] = None
    elif problem == "raw":
        call = call.model_copy(update={"unsupported": True})
    elif problem == "policy":
        env.policy.decision = PolicyDecisionType.REQUIRE_APPROVAL
    elif problem == "revoked":
        env.revoked = True
    elif problem == "stale":
        env.leases.release(env.session, fence=env.fence)
    before = queue(env)
    with pytest.raises((ValueError, LeaseLostError)):
        env.callback(call, **kwargs)
    assert queue(env) == before
    assert not env.transport.creates


def test_unknown_never_reissues(effect):
    env = effect
    env.transport.unknown = True
    call, kwargs = invocation(env)
    with pytest.raises(ValueError):
        env.callback(call, **kwargs)
    before = queue(env)
    with pytest.raises(EffectDispatchStateError, match="no reissue"):
        CloudCoverageEffectInvoke(**env.callback_kwargs)(call, **kwargs)
    assert queue(env) == before
    assert len(env.transport.creates) == 1


@pytest.mark.parametrize("replay", [False, True])
def test_stop_before_transport_or_replay(effect, replay):
    env = effect
    call, kwargs = invocation(env)
    if replay:
        env.callback(call, **kwargs)
    command = SessionCommand(
        session_id=env.session,
        kind=SessionCommandKind.STOP,
        expected_revision=env.revision,
        idempotency_key="callback-stop",
    )
    event = SessionEvent.create(
        session_id=env.session,
        sequence=env.revision + 1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
    )
    env.events.append(event)
    env.revision = event.sequence
    before = queue(env)
    with pytest.raises(ValueError, match="STOP"):
        env.callback(call, **kwargs)
    assert queue(env) == before
    assert len(env.transport.creates) == int(replay)


def test_constructor_rejects_non_cloud_admission():
    with pytest.raises(ValueError, match="Cloud Effect"):
        CloudCoverageEffectInvoke(
            payloads=object(),
            gateway=None,
            admission=None,
            binding=None,
            context=None,
            fence=None,
            authority=None,
            policy=None,
            check_authority=None,
            next_event=None,
            accept_event=None,
        )


@pytest.mark.parametrize(
    "problem",
    [
        "binding",
        "admission",
        "host_context",
        "scope",
        "descriptor",
        "result_id",
        "result_extra",
        "receipt_bool",
        "receipt_float",
    ],
)
def test_persistent_corruption_denies_replay_without_transport(effect, problem):
    env = effect
    call, kwargs = invocation(env)
    env.callback(call, **kwargs)
    with psycopg.connect(env.dsn, row_factory=dict_row) as connection:
        if problem == "binding":
            row = connection.execute("SELECT snapshot_json FROM task_binding_snapshots").fetchone()
            raw = row["snapshot_json"]
            raw["binding_revision"] += 1
            connection.execute("UPDATE task_binding_snapshots SET snapshot_json=%s", (Jsonb(raw),))
        elif problem in {"admission", "host_context"}:
            row = connection.execute(
                "SELECT payload FROM session_events WHERE event_type=%s",
                (EventType.TASK_PREPARED.value,),
            ).fetchone()
            raw = row["payload"]
            if problem == "admission":
                raw["coverage_admission"]["max_model_calls"] = True
            else:
                raw["host_context"]["grant_id"] = "foreign"
            connection.execute(
                "UPDATE session_events SET payload=%s WHERE event_type=%s",
                (Jsonb(raw), EventType.TASK_PREPARED.value),
            )
        elif problem == "scope":
            raw = call.arguments.copy()
            raw["contract_digest"] = "a" * 64
            call = call.model_copy(update={"arguments": raw})
        else:
            row = connection.execute("SELECT result FROM effect_outbox").fetchone()
            raw = row["result"]
            if problem == "descriptor":
                raw["output"] = "Host Effect reconciled from its durable receipt."
            elif problem == "result_id":
                raw["tool_call_id"] = str(new_tool_call_id())
            elif problem == "result_extra":
                raw["extra"] = True
            else:
                raw["receipt"]["output_bytes"] = True if problem == "receipt_bool" else 1.0
            connection.execute("UPDATE effect_outbox SET result=%s", (Jsonb(raw),))
    before = persisted(env)
    with pytest.raises(ValueError):
        env.callback(call, **kwargs)
    assert persisted(env) == before
    assert len(env.transport.creates) == 1


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("problem", ["session_namespace", "metadata_deployment"])
def test_namespace_mismatch_denies_constructor_and_invocation_unchanged(effect, replay, problem):
    env = effect
    call, kwargs = invocation(env)
    if replay:
        env.callback(call, **kwargs)
        assert all(
            row["deployment_namespace"] == NAMESPACE and row["session_id"] == env.session
            for row in persisted(env)["artifact_payload_metadata"]
        )
    if problem == "session_namespace":
        with psycopg.connect(env.dsn) as connection:
            connection.execute(
                """UPDATE session_projections SET namespace_id=%s
                   WHERE deployment_namespace=%s AND session_id=%s""",
                ("foreign-host", NAMESPACE, env.session),
            )
    else:
        env.artifacts._metadata_store = PostgresCloudArtifactPayloadStore(
            env.dsn, deployment_namespace="foreign-deployment"
        )
    before = persisted(env)
    with pytest.raises(ValueError):
        CloudCoverageEffectInvoke(**env.callback_kwargs)
    assert persisted(env) == before
    with pytest.raises(ValueError):
        env.callback(call, **kwargs)
    assert persisted(env) == before
    assert len(env.transport.creates) == int(replay)


def replace_worker(env):
    env.leases.release(env.session, fence=env.fence)
    env.fence = env.leases.acquire(
        env.session, owner_instance_id="artifact-replay-worker", ttl=timedelta(minutes=5)
    ).fence
    env.callback_kwargs["fence"] = env.fence
    return CloudCoverageEffectInvoke(**env.callback_kwargs)


def test_missing_finalized_original_output_denies_replacement_replay(effect):
    env = effect
    call, kwargs = invocation(env)
    original = env.callback(call, **kwargs)
    # Remove only the terminal output, leaving the durable request object intact.
    output_key = next(
        key
        for method, data in env.client.calls
        if method == "put_object"
        if (key := data["Key"]) and env.client.objects[key]["Body"] == original.output.encode()
    )
    del env.client.objects[output_key]
    callback = replace_worker(env)
    before = persisted(env)
    puts = sum(method == "put_object" for method, _ in env.client.calls)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        callback(call, **kwargs)
    assert persisted(env) == before
    assert sum(method == "put_object" for method, _ in env.client.calls) == puts
    assert len(env.transport.creates) == 1


def test_modified_inline_descriptor_denies_replacement_replay(effect):
    env = effect
    call, kwargs = invocation(env)
    original = env.callback(call, **kwargs)
    with psycopg.connect(env.dsn, row_factory=dict_row) as connection:
        row = connection.execute(
            """SELECT dispatch_id, result FROM effect_outbox
               WHERE deployment_namespace=%s AND execution_session_id=%s""",
            (NAMESPACE, env.session),
        ).fetchone()
        raw = row["result"]
        descriptor = json.loads(raw["output"])
        descriptor["snapshot"]["snapshot_id"] = "another-valid-snapshot"
        connection.execute(
            """UPDATE effect_outbox
               SET result=jsonb_set(result,'{output}',to_jsonb(%s::text),false)
               WHERE deployment_namespace=%s AND dispatch_id=%s""",
            (json.dumps(descriptor), NAMESPACE, row["dispatch_id"]),
        )
    assert any(item["Body"] == original.output.encode() for item in env.client.objects.values())
    callback = replace_worker(env)
    before = persisted(env)
    puts = sum(method == "put_object" for method, _ in env.client.calls)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        callback(call, **kwargs)
    assert persisted(env) == before
    assert sum(method == "put_object" for method, _ in env.client.calls) == puts
    assert len(env.transport.creates) == 1
