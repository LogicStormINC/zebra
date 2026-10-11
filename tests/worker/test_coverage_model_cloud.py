"""MODEL callback acceptance against actual PostgreSQL, fixture S3 and HTTP only."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import httpx
import psycopg
import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.cloud_artifact_requests import (
    ArtifactMetadataQuery,
    canonical_artifact_reserve_hash,
)
from agent_core.domain.coverage_contracts import CoverageRefusedError, coverage_digest
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    decode_model_checkpoint,
)
from agent_core.domain.coverage_persistence import canonical_coverage_bytes
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId
from agent_integrations.coverage_model_completion import (
    decode_model_completion,
    encode_model_completion,
)
from agent_integrations.coverage_model_policy import (
    POLICY_KIND,
    REVIEWER_PROFILE,
    OfficialDeepSeekPolicy,
)
from agent_storage import PostgresSessionArtifactReadStore

from tests.agent_integrations.test_coverage_model_invocation import invoke, messages
from tests.agent_storage.test_postgres_command_wakeup import (  # noqa: F401
    NAMESPACE,
    dsn,
    postgres_dsn,
)
from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    CAPACITY,
    METADATA,
    compose,
    model_cloud,
)


def database_state(env):
    """Raw PG evidence, independently of budget replay."""
    with psycopg.connect(env.dsn) as connection:
        ledger = connection.execute(
            "SELECT calls,charged_tokens,unresolved FROM coverage_model_ledger WHERE run_id=%s",
            (env.binding.run_id,),
        ).fetchone()
        calls = connection.execute(
            "SELECT reservation,receipt,reserved_sequence,receipt_sequence "
            "FROM coverage_model_calls "
            "WHERE run_id=%s ORDER BY reservation_key",
            (env.binding.run_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT event_type,count(*) FROM session_events WHERE session_id=%s "
            "AND event_type IN ('coverage_model_budget_initialized','coverage_model_call_reserved',"
            "'coverage_model_usage_recorded') GROUP BY event_type ORDER BY event_type",
            (env.session,),
        ).fetchall()
        witnesses = connection.execute(
            "SELECT count(*) FROM coverage_model_events WHERE run_id=%s",
            (env.binding.run_id,),
        ).fetchone()[0]
        units = connection.execute(
            "SELECT count(*) FROM coverage_units WHERE run_id=%s AND result IS NOT NULL",
            (env.binding.run_id,),
        ).fetchone()[0]
    return ledger, calls, events, witnesses, units


def private_artifact(env, kind):
    assert (
        PostgresSessionArtifactReadStore(
            env.dsn,
            deployment_namespace=NAMESPACE,
        ).list_for_session(env.session)
        == []
    ), "private MODEL evidence entered public Session artifacts"
    with psycopg.connect(env.dsn) as connection:
        rows = connection.execute(
            "SELECT artifact_id FROM artifact_payload_metadata WHERE session_id=%s AND kind=%s",
            (env.session, kind),
        ).fetchall()
    assert len(rows) == 1
    identifier = ArtifactId(rows[0][0])
    record = env.cloud.metadata.get_metadata(
        ArtifactMetadataQuery(
            deployment_namespace=NAMESPACE,
            session_id=env.session,
            artifact_id=identifier,
        )
    )
    assert record.lifecycle_status == CloudArtifactPayloadLifecycleStatus.FINALIZED
    assert record.lifecycle_revision == 2 and record.session_id == env.session
    assert record.reservation.mime_type == "application/json"
    assert record.reservation.retained_until == env.binding.snapshot.expires_at
    body = env.cloud.read_payload_bytes(identifier)
    assert canonical_coverage_bytes(json.loads(body)) == body
    assert record.reservation.sha256 == sha256(body).hexdigest()
    materialized = [
        e
        for e in env.events.list_for_session(env.session)
        if e.event_type == EventType.COVERAGE_ARTIFACT_MATERIALIZED
        and e.payload["metadata"]["artifact_uri"] == record.uri
    ]
    assert len(materialized) == 1
    event = materialized[0]
    assert event.event_id == record.event_binding.event_id
    assert event.sequence == record.event_binding.sequence
    assert event.sequence == record.reservation.intended_event_sequence
    assert event.event_type == EventType.COVERAGE_ARTIFACT_MATERIALIZED
    assert event.actor == EventActor.SYSTEM
    assert event.payload["namespace"] == env.binding.namespace
    assert event.payload["run_id"] == env.binding.run_id
    assert event.payload["metadata"]["artifact_uri"] == record.uri == f"artifact://{identifier}"
    assert event.payload["sha256"] == sha256(body).hexdigest()
    assert event.payload["reservation"] == canonical_artifact_reserve_hash(
        NAMESPACE, record.reservation
    )
    assert (
        env.objects.read_version_verified(
            record.object_receipt.expectation,
            record.object_receipt.object_version,
        )
        == body
    )
    assert json.loads(body)["scope"] == "internal"
    return identifier, body


def assert_settled(env, response):
    state = database_state(env)
    assert state[0] == (1, 30, 0) and len(state[1]) == 1
    assert dict(state[2]) == {
        "coverage_model_budget_initialized": 1,
        "coverage_model_call_reserved": 1,
        "coverage_model_usage_recorded": 1,
    }
    assert state[3:] == (3, 0)  # No semantic unit transaction gate is claimed here.
    reservation, receipt, reserved_sequence, receipt_sequence = state[1][0]
    assert reservation["reservation_key"] == "model-" + coverage_digest(
        {
            "binding": env.binding.model_dump(mode="json"),
            "unit": env.key.model_dump(mode="json"),
        }
    )
    assert reservation["token_bound"] == CAPACITY
    assert reservation["model_profile"] == REVIEWER_PROFILE
    assert reservation["request_digest"] == sha256(env.requests[0].content).hexdigest()
    identifier, body = private_artifact(env, MODEL_CHECKPOINT_KIND)
    assert json.loads(body)["schema"] == "coverage-model-checkpoint/2"
    checkpoint = decode_model_checkpoint(body)
    assert checkpoint.binding == env.binding
    assert checkpoint.reservation.model_dump(mode="json") == reservation
    assert checkpoint.request == env.requests[0].content
    assert checkpoint.completion == encode_model_completion(response)
    assert (
        encode_model_completion(decode_model_completion(checkpoint.completion))
        == checkpoint.completion
    )
    assert response.assistant_message.provider_reasoning_content == "私有完整推理🙂"
    assert response.call_metadata.usage.input_tokens == 10
    assert response.call_metadata.usage.output_tokens == 20
    assert response.call_metadata.usage.total_tokens == 30
    assert response.call_metadata.usage.reasoning_tokens == 3
    assert response.call_metadata.usage.prompt_cache_hit_tokens == 4
    assert response.call_metadata.usage.prompt_cache_miss_tokens == 6
    assert response.call_metadata.profile_id == REVIEWER_PROFILE
    assert response.call_metadata.request_hash == reservation["request_digest"]
    assert response.call_metadata.retry_count == 0
    assert receipt["input_tokens"] == 10 and receipt["output_tokens"] == 20
    assert receipt["total_tokens"] == 30
    assert receipt["checkpoint_ref"] == f"artifact://{identifier}"
    assert receipt["checkpoint_digest"] == sha256(body).hexdigest()
    assert reserved_sequence < receipt_sequence
    policy_id, policy_bytes = private_artifact(env, POLICY_KIND)
    policy = json.loads(policy_bytes)
    assert policy["metadata"] == json.dumps(METADATA)
    assert policy["original_policy"] == env.policy.model_dump(mode="json")
    assert policy["effective"] == env.proof.effective
    assert env.policy.max_tokens == env.host.limits.max_model_tokens == CAPACITY * 2
    assert env.policy.deadline == env.policy.started_at + timedelta(
        seconds=env.admission.max_runtime_seconds,
    )
    origin = next(
        e
        for e in env.events.list_for_session(env.session)
        if e.event_type == EventType.TASK_PREPARED
    )
    assert env.policy.started_at == origin.created_at
    assert policy_id != identifier and len(env.client.objects) == 3
    request = env.requests[0]
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.method == "POST"
    wire = json.loads(request.content)
    assert wire["model"] == "deepseek-v4-pro"
    assert wire["max_tokens"] == 8192 and wire["stream"] is False
    assert "tools" not in wire
    assert wire["messages"][0]["content"] == env.definition.instructions
    assert wire["messages"][1]["content"] == messages(env)[1].content
    return state


def test_pristine_invoke_settled_exact_replay_and_fresh_composition(model_cloud):  # noqa: F811
    env = model_cloud
    first_composition = compose(env)
    initial = database_state(env)
    assert initial == ((0, 0, 0), [], [("coverage_model_budget_initialized", 1)], 1, 0)
    first = invoke(env, first_composition)
    before = assert_settled(env, first)
    replay = invoke(env, first_composition)
    assert encode_model_completion(replay) == encode_model_completion(first)
    assert assert_settled(env, replay) == before
    old_fence = env.fence
    fresh = compose(env, replacement=True)
    assert env.fence != old_fence
    replay = invoke(env, fresh)
    assert encode_model_completion(replay) == encode_model_completion(first)
    assert assert_settled(env, replay) == before
    assert database_state(env) == before and len(env.requests) == 1


@pytest.mark.parametrize("stage", ["reserved", "http", "checkpoint", "settled"])
def test_durable_crash_windows_never_authorize_second_http(
    model_cloud,  # noqa: F811
    monkeypatch,
    stage,
):  # noqa: F811
    env = model_cloud
    composed = compose(env)
    with monkeypatch.context() as patch:
        if stage == "reserved":
            original = env.store.reserve_model_call

            def crash(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError("crash after durable reservation")

            patch.setattr(env.store, "reserve_model_call", crash)
        elif stage == "http":
            env.reply = httpx.ReadTimeout("unknown HTTP outcome")
        else:
            original = env.store.record_model_usage

            def crash(*args, **kwargs):
                if stage == "settled":
                    original(*args, **kwargs)
                raise RuntimeError("usage acknowledgement lost")

            patch.setattr(env.store, "record_model_usage", crash)
        with pytest.raises(CoverageRefusedError):
            invoke(env, composed)
    before = database_state(env)
    assert before[0] == ((1, 30, 0) if stage == "settled" else (1, CAPACITY, 1))
    assert len(before[1]) == 1 and len(env.requests) == (0 if stage == "reserved" else 1)
    original_bytes = (
        private_artifact(env, MODEL_CHECKPOINT_KIND)[1]
        if stage
        in {
            "checkpoint",
            "settled",
        }
        else None
    )
    fresh = compose(env, replacement=True)
    if original_bytes is not None:
        response = invoke(env, fresh)
        assert decode_model_checkpoint(original_bytes).completion == encode_model_completion(
            response
        )
        assert private_artifact(env, MODEL_CHECKPOINT_KIND)[1] == original_bytes
        assert_settled(env, response)
        replay = invoke(env, compose(env))
        assert replay.assistant_message == response.assistant_message
        assert_settled(env, replay)
    else:
        with pytest.raises(CoverageRefusedError, match="unresolved_failure"):
            invoke(env, fresh)
        assert database_state(env) == before
    assert len(env.requests) == (0 if stage == "reserved" else 1)
    assert database_state(env)[1][0][0] == before[1][0][0]


@pytest.mark.parametrize("conflict", ["source", "wire", "proof", "checkpoint"])
def test_changed_original_evidence_refuses_without_second_http(model_cloud, conflict):  # noqa: F811
    env = model_cloud
    invoke(env, compose(env))
    before = database_state(env)
    if conflict == "proof":
        altered = json.loads(json.dumps(METADATA))
        altered["data"][0]["context_window"] += 1
        with pytest.raises(CoverageRefusedError):
            compose(env, proof=OfficialDeepSeekPolicy(json.dumps(altered).encode()))
    else:
        fresh = compose(env)
        if conflict == "source":
            env.source = "changed source"
        elif conflict == "checkpoint":
            identifier, _ = private_artifact(env, MODEL_CHECKPOINT_KIND)
            record = env.cloud.metadata.get_metadata(
                ArtifactMetadataQuery(
                    deployment_namespace=NAMESPACE,
                    session_id=env.session,
                    artifact_id=identifier,
                )
            )
            # Corrupt only the fixture object; retain actual PG hashes and Event proof.
            for value in env.client.objects.values():
                if sha256(value["Body"]).hexdigest() == record.reservation.sha256:
                    value["Body"] = b"corrupt checkpoint"
        with pytest.raises(CoverageRefusedError):
            invoke(env, fresh, indent=2 if conflict == "wire" else None)
    assert database_state(env) == before and len(env.requests) == 1


@pytest.mark.parametrize("boundary", ["stop", "revoked", "fence", "late_fence", "deadline"])
def test_current_authority_and_original_deadline_refuse(
    model_cloud,  # noqa: F811
    monkeypatch,
    boundary,
):  # noqa: F811
    env = model_cloud
    composed = compose(env)
    if boundary == "stop":
        revision = env.events.list_for_session(env.session)[-1].sequence
        command = SessionCommand(
            session_id=env.session,
            kind=SessionCommandKind.STOP,
            expected_revision=revision,
            idempotency_key="stop-fixture",
        )
        env.events.append(
            SessionEvent.create(
                session_id=env.session,
                sequence=revision + 1,
                actor=EventActor.USER,
                event_type=EventType.SESSION_COMMAND_ACCEPTED,
                payload=command.event_payload(),
            )
        )
    elif boundary == "revoked":
        env.wire.revoked = True
    elif boundary == "fence":
        env.leases.release(env.session, fence=env.fence)
        env.leases.acquire(env.session, owner_instance_id="other", ttl=timedelta(minutes=5))
    elif boundary == "deadline":
        monkeypatch.setattr(composed, "now", lambda: env.policy.deadline)
    else:
        original = env.store.reserve_model_call

        def late(*args, **kwargs):
            result = original(*args, **kwargs)
            env.leases.release(env.session, fence=env.fence)
            env.leases.acquire(env.session, owner_instance_id="other", ttl=timedelta(minutes=5))
            return result

        monkeypatch.setattr(env.store, "reserve_model_call", late)
    with pytest.raises(CoverageRefusedError):
        invoke(env, composed)
    assert not env.requests
    state = database_state(env)
    assert state[0] == ((1, CAPACITY, 1) if boundary == "late_fence" else (0, 0, 0))
    assert dict(state[2]).get("coverage_model_usage_recorded", 0) == 0


def test_fence_lost_after_http_keeps_full_charge_and_refuses_replay(model_cloud):  # noqa: F811
    env = model_cloud
    composed = compose(env)

    def lose_fence():
        env.leases.release(env.session, fence=env.fence)
        env.leases.acquire(env.session, owner_instance_id="other", ttl=timedelta(minutes=5))

    env.http_boundary = lose_fence
    with pytest.raises(CoverageRefusedError):
        invoke(env, composed)
    assert database_state(env)[0] == (1, CAPACITY, 1)
    env.http_boundary = None
    env.fence = env.leases.get(env.session).fence
    with pytest.raises(CoverageRefusedError):
        invoke(env, compose(env))
    assert len(env.requests) == 1 and database_state(env)[0] == (1, CAPACITY, 1)


@pytest.mark.parametrize("model_cloud", [30], indirect=True)
@pytest.mark.parametrize("phase", ["settled", "http"])
def test_database_clock_original_deadline_blocks_late_response_and_replay(
    model_cloud,  # noqa: F811
    phase,
    monkeypatch,
):
    env = model_cloud
    composed = compose(env)

    def expire():
        with psycopg.connect(env.dsn) as connection:
            connection.execute(
                "SELECT pg_sleep(greatest(0,extract(epoch FROM "
                "(%s::timestamptz-clock_timestamp())))+0.05)",
                (env.policy.deadline,),
            )
            assert (
                connection.execute("SELECT clock_timestamp()").fetchone()[0] > env.policy.deadline
            )

    if phase == "settled":
        invoke(env, composed)
        pinned = datetime.now(UTC)
        assert env.policy.started_at <= pinned < env.policy.deadline
        expire()
    else:
        env.http_boundary = expire
        with pytest.raises(CoverageRefusedError):
            invoke(env, composed)
    before = database_state(env)
    assert before[0] == ((1, 30, 0) if phase == "settled" else (1, CAPACITY, 1))
    if phase == "settled":
        history = env.events.list_for_session(env.session)
        with monkeypatch.context() as clock:
            clock.setattr(composed, "now", lambda: pinned)
            assert composed._time() == pinned  # Python deadline/retention still permit replay.
            with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
                invoke(env, composed)
            assert database_state(env) == before
            assert env.events.list_for_session(env.session) == history
            assert len(env.requests) == 1
    with pytest.raises(CoverageRefusedError):
        invoke(env, composed)
    with pytest.raises(CoverageRefusedError):
        compose(env, replacement=True)
    assert database_state(env) == before and len(env.requests) == 1
