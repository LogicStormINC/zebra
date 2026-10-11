"""Isolated real PG lifecycle, with the existing fake versioned object store."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event

import psycopg
import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadNotFoundError
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    CoverageModelCheckpoint,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage
from agent_integrations.coverage_model_completion import encode_model_completion
from agent_storage import (
    PostgresCloudArtifactPayloadStore,
    PostgresEventStore,
    S3ArtifactObjectStore,
)
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher

from tests.agent_storage.coverage_model_proof_fixtures import (  # noqa: F401
    original_object,
    proof_env,
    source_counts,
)
from tests.agent_storage.test_coverage_artifact_publication import _authority
from tests.agent_storage.test_coverage_model_budget import (  # noqa: F401
    charge,
    dsn,
    postgres_dsn,
    reserve,
    spend,
)
from tests.agent_storage.test_coverage_model_budget import model_env as checkpoint_env  # noqa: F401
from tests.agent_storage.test_coverage_publication import _certify, _prepare_publication, _read
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_s3_artifact_objects import _FakeS3Client
from tests.worker.test_coverage_artifacts import facade


@pytest.fixture
def model_env(checkpoint_env):  # noqa: F811
    return checkpoint_env


def publish_checkpoint(
    env,
    request,
    *,
    completion=None,
    publish=True,
    transform=None,
    retained_until=None,
):
    if not hasattr(env, "cloud"):
        env.events = PostgresEventStore(env.dsn, deployment_namespace=NAMESPACE)
        env.metadata = PostgresCloudArtifactPayloadStore(env.dsn, deployment_namespace=NAMESPACE)
        env.client = _FakeS3Client()
        env.objects = S3ArtifactObjectStore(env.client, bucket="checkpoint-tests")
        env.publisher = PostgresCoverageArtifactPublisher(
            env.dsn, deployment_namespace=NAMESPACE, metadata=env.metadata, objects=env.objects
        )
        env.cloud = facade(env)
        env.checkpoints = {}
        local_get, local_read = env.artifacts.get_payload, env.artifacts.read_payload_bytes_bounded
        # Existing manifest/report fixtures are SQLite; checkpoints use the actual
        # Cloud facade/PG lifecycle and versioned object reader exclusively.
        env.artifacts.get_payload = lambda ident: (
            env.cloud.get_payload(ident) if ident in env.checkpoints else local_get(ident)
        )
        env.artifacts.read_payload_bytes_bounded = lambda ident, *, max_bytes: (
            env.cloud.read_payload_bytes_bounded(ident, max_bytes=max_bytes)
            if ident in env.checkpoints
            else local_read(ident, max_bytes=max_bytes)
        )
    completion = completion or encode_model_completion(
        ModelCompletion(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="clear",
                created_at=datetime.now(UTC),
                provider_reasoning_content="private original evidence",
            ),
            call_metadata=ModelCallMetadata(
                usage=ModelUsage(3, 7, 10),
                profile_id=request.model_profile,
                request_hash=request.request_digest,
            ),
        )
    )
    checkpoint = CoverageModelCheckpoint(env.binding, request, completion)
    prior = env.checkpoints.get(checkpoint.artifact_id)
    if prior is not None:
        return prior
    body = checkpoint.canonical_bytes
    if transform is not None:
        body = transform(body)
    receipt = CoverageModelUsageReceipt(
        reservation=request,
        input_tokens=3,
        output_tokens=7,
        total_tokens=10,
        checkpoint_ref=f"artifact://{checkpoint.artifact_id}",
        checkpoint_digest=sha256(body).hexdigest(),
    )
    env.checkpoints[checkpoint.artifact_id] = receipt
    env.checkpoint = checkpoint
    env.payload = ArtifactPayloadWrite(
        session_id=env.session.session_id,
        kind=MODEL_CHECKPOINT_KIND,
        mime_type="application/json",
        payload=body,
        created_at=datetime.now(UTC),
        retained_until=retained_until or env.binding.snapshot.expires_at,
    )
    if publish:
        env.cloud.store_payload_immutable(env.payload, artifact_id=checkpoint.artifact_id)
    return receipt


def settle(env, receipt):
    return env.store.record_model_usage(env.binding, receipt, fence=env.fence)


def ledger(env):
    with psycopg.connect(env.dsn) as connection:
        return connection.execute(
            "SELECT calls,charged_tokens,unresolved FROM coverage_model_ledger WHERE run_id=%s",
            (env.binding.run_id,),
        ).fetchone()


def test_original_proof_settles_and_replays_after_worker_replacement(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    receipt = publish_checkpoint(env, request)
    sequence = settle(env, receipt)
    env.leases.release(env.session.session_id, fence=env.fence)
    env.fence = env.leases.acquire(
        env.session.session_id, owner_instance_id="replacement", ttl=timedelta(minutes=5)
    ).fence
    env.store = PostgresCoverageStore(
        env.dsn,
        deployment_namespace=NAMESPACE,
        artifacts=env.artifacts,
        supported_model_profiles=("review",),
    )
    assert settle(env, receipt) == sequence and charge(env) == (1, 10, 0)
    assert not spend(env, request).invoke
    altered = replace(env.checkpoint, completion=env.checkpoint.completion + b"\n")
    with pytest.raises(ValueError, match="immutable publication conflicts"):
        env.cloud.store_payload_immutable(
            env.payload.model_copy(update={"payload": altered.canonical_bytes}),
            artifact_id=altered.artifact_id,
        )


def test_legacy_missing_proof_retains_full_charge(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    receipt = CoverageModelUsageReceipt(
        reservation=request, input_tokens=3, output_tokens=4, total_tokens=10
    )
    before = source_counts(env)
    with pytest.raises(ValueError, match="original checkpoint"):
        settle(env, receipt)
    assert ledger(env) == (1, 70, 1) and source_counts(env) == before


@pytest.mark.parametrize(
    "damage",
    [
        "event_missing",
        "namespace",
        "run",
        "event_id",
        "sequence",
        "reservation",
        "sha256",
        "uri",
        "actor",
        "duplicate",
        "staged",
        "pruned",
        "metadata_event",
        "metadata_sequence",
        "metadata_length",
        "foreign_session",
        "bytes",
        "missing_object",
        "missing_metadata",
        "expired",
        "wrong_kind",
    ],
)
@pytest.mark.parametrize("settled", [False, True])
def test_missing_corrupt_foreign_conflicting_proof_denies_settlement_replay(
    model_env,
    damage,
    settled,
):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    receipt = publish_checkpoint(env, request)
    if settled:
        settle(env, receipt)
    damage_checkpoint(env, damage)
    before, balance = source_counts(env), ledger(env)
    with pytest.raises(
        (ValueError, RuntimeError, FileNotFoundError, CloudArtifactPayloadNotFoundError)
    ):
        settle(env, receipt)
    if settled:
        with pytest.raises(
            (ValueError, RuntimeError, FileNotFoundError, CloudArtifactPayloadNotFoundError)
        ):
            spend(env, request)
    assert ledger(env) == balance and source_counts(env) == before


def damage_checkpoint(env, damage):
    ref = f"artifact://{env.checkpoint.artifact_id}"
    if damage == "bytes":
        env.client.objects[original_object(env)]["Body"] = b"corrupt"
        return
    if damage == "missing_object":
        del env.client.objects[original_object(env)]
        return
    with psycopg.connect(env.dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        if damage == "event_missing":
            connection.execute(
                "DELETE FROM session_events WHERE payload->'metadata'->>'artifact_uri'=%s", (ref,)
            )
        elif damage in {"namespace", "run", "reservation", "sha256", "uri"}:
            field = {"run": "run_id", "uri": "metadata"}.get(damage, damage)
            from psycopg.types.json import Jsonb

            value = {"artifact_uri": "artifact://wrong"} if damage == "uri" else "f" * 64
            connection.execute(
                "UPDATE session_events SET payload=payload || %s WHERE "
                "payload->'metadata'->>'artifact_uri'=%s",
                (Jsonb({field: value}), ref),
            )
        elif damage in {"event_id", "sequence", "actor", "foreign_session"}:
            assignments = {
                "event_id": "event_id=gen_random_uuid()",
                "sequence": "sequence=sequence+100",
                "actor": "actor='harness'",
                "foreign_session": "session_id=gen_random_uuid()",
            }
            connection.execute(
                f"UPDATE session_events SET {assignments[damage]} "
                "WHERE payload->'metadata'->>'artifact_uri'=%s",
                (ref,),
            )
        elif damage == "missing_metadata":
            connection.execute(
                "DELETE FROM artifact_payload_metadata WHERE artifact_id=%s",
                (env.checkpoint.artifact_id,),
            )
        elif damage == "duplicate":
            origin = next(
                event
                for event in env.events.list_for_session(env.session.session_id)
                if event.payload.get("metadata", {}).get("artifact_uri") == ref
            )
            env.events.append(
                SessionEvent.create(
                    session_id=env.session.session_id,
                    sequence=_authority(env).expected_stream_revision + 1,
                    event_type=EventType.COVERAGE_ARTIFACT_MATERIALIZED,
                    actor=EventActor.SYSTEM,
                    payload=origin.payload,
                )
            )
        else:
            assignments = {
                "staged": "lifecycle_status='staged',lifecycle_revision=1,event_id=NULL,"
                "event_sequence=NULL,artifact_uri=NULL,finalized_at=NULL",
                "pruned": "lifecycle_status='pruned',lifecycle_revision=4,"
                "pruning_at=clock_timestamp(),pruned_at=clock_timestamp()",
                "metadata_event": "event_id=gen_random_uuid()",
                "metadata_sequence": "event_sequence=event_sequence+1,"
                "intended_event_sequence=intended_event_sequence+1,"
                "expected_stream_revision=expected_stream_revision+1",
                "metadata_length": "size_bytes=size_bytes+1",
                "expired": "retained_until=request_created_at",
                "wrong_kind": "kind='coverage-report'",
            }
            connection.execute(
                f"UPDATE artifact_payload_metadata SET {assignments[damage]} WHERE artifact_id=%s",
                (env.checkpoint.artifact_id,),
            )


@pytest.mark.parametrize("gate", ["issue", "retry", "read", "rebuild"])
@pytest.mark.parametrize(
    "damage", ["event_missing", "bytes", "missing_object", "pruned", "namespace", "reservation"]
)
def test_certificate_lifecycle_rechecks_original_checkpoint(proof_env, gate, damage):  # noqa: F811
    env = proof_env()
    if gate != "issue":
        _certify(env)
    damage_checkpoint(env, damage)
    before, balance = source_counts(env), ledger(env)
    with pytest.raises(
        (ValueError, RuntimeError, FileNotFoundError, CloudArtifactPayloadNotFoundError)
    ):
        if gate in {"issue", "retry"}:
            _certify(env)
        elif gate == "read":
            _read(env)
        else:
            env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert source_counts(env) == before and ledger(env) == balance


def test_valid_checkpoint_does_not_establish_semantic_unit_coverage(model_env, monkeypatch):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    settle(env, publish_checkpoint(env, request))
    _prepare_publication(env)
    def forbidden(*args):
        pytest.fail("incomplete coverage must refuse before full publication proof")
    monkeypatch.setattr(env.store, "_check_publication_lifecycle", forbidden)
    with pytest.raises(ValueError, match="incomplete"):
        _certify(env)


def test_invalid_header_or_receipt_never_refunds(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    receipt = publish_checkpoint(env, request)
    before = source_counts(env)
    for changes in (
        {"output_tokens": 4},
        {"checkpoint_digest": "f" * 64},
        {"checkpoint_ref": None, "checkpoint_digest": None},
    ):
        with pytest.raises(ValueError):
            settle(env, receipt.model_copy(update=changes))
    assert ledger(env) == (1, 70, 1) and source_counts(env) == before


@pytest.mark.parametrize(
    "variant",
    [
        "foreign_binding",
        "foreign_request",
        "scope",
        "schema",
        "usage",
        "usage_bool",
        "duplicate",
        "nonfinite",
        "utf8",
        "profile",
        "request_hash",
    ],
)
def test_finalized_object_with_invalid_envelope_cannot_refund(model_env, variant):
    from agent_core.domain.coverage_persistence import canonical_coverage_bytes

    env = model_env()
    request = reserve(env)
    spend(env, request)

    def transform(body):
        data = json.loads(body)
        if variant == "foreign_binding":
            data["binding"]["run_id"] = "foreign"
        elif variant == "foreign_request":
            data["reservation"]["request_digest"] = "f" * 64
        elif variant in {"scope", "schema"}:
            data[variant] = "unknown"
        elif variant in {"profile", "request_hash"}:
            completion = json.loads(data["completion"])
            field = "profile_id" if variant == "profile" else variant
            completion["completion"]["call_metadata"][field] = "foreign"
            data["completion"] = canonical_coverage_bytes(completion).decode()
        elif variant in {"usage", "usage_bool"}:
            completion = json.loads(data["completion"])
            completion["completion"]["call_metadata"]["usage"]["input_tokens"] = (
                True if variant == "usage_bool" else 2
            )
            data["completion"] = canonical_coverage_bytes(completion).decode()
        elif variant == "duplicate":
            return b'{"scope":"internal",' + body[1:]
        elif variant == "nonfinite":
            return body.replace(b'"scope":"internal"', b'"scope":NaN')
        else:
            return b"\xff"
        return canonical_coverage_bytes(data)

    receipt = publish_checkpoint(env, request, transform=transform)
    before = source_counts(env)
    with pytest.raises(ValueError):
        settle(env, receipt)
    assert ledger(env) == (1, 70, 1) and source_counts(env) == before


def test_upload_crash_has_no_receipt_authority_and_recovers_original_bytes(model_env, monkeypatch):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    receipt = publish_checkpoint(env, request, publish=False)
    original = env.objects.put_if_absent

    def crash(*args):
        original(*args)
        raise RuntimeError("crash after upload")

    with monkeypatch.context() as patch:
        patch.setattr(env.objects, "put_if_absent", crash)
        with pytest.raises(RuntimeError):
            env.cloud.store_payload_immutable(env.payload, artifact_id=env.checkpoint.artifact_id)
    before = source_counts(env)
    with pytest.raises(ValueError):
        settle(env, receipt)
    assert ledger(env) == (1, 70, 1) and source_counts(env) == before
    env.leases.release(env.session.session_id, fence=env.fence)
    env.fence = env.leases.acquire(
        env.session.session_id, owner_instance_id="recovered", ttl=timedelta(minutes=5)
    ).fence
    env.cloud.store_payload_immutable(env.payload, artifact_id=env.checkpoint.artifact_id)
    settle(env, receipt)
    assert charge(env) == (1, 10, 0) and len(env.client.objects) == 1


@pytest.mark.parametrize("value", [None, True, 1, "g" * 64, "a" * 63])
def test_previous_reservation_requires_raw_canonical_digest(model_env, value):
    from psycopg.types.json import Jsonb

    env = model_env()
    request = reserve(env)
    spend(env, request)
    receipt = publish_checkpoint(env, request)
    with psycopg.connect(env.dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        connection.execute(
            "UPDATE session_events SET payload=payload || %s WHERE "
            "payload->'metadata'->>'artifact_uri'=%s",
            (Jsonb({"previous_reservation": value}), receipt.checkpoint_ref),
        )
    before = source_counts(env)
    with pytest.raises(ValueError, match="strict digest"):
        settle(env, receipt)
    assert ledger(env) == (1, 70, 1) and source_counts(env) == before


@pytest.mark.parametrize(
    "phase", ["first", "replay", "callback_late", "reservation_replay", "reservation_callback_late"]
)
def test_original_deadline_blocks_first_or_replayed_usage_and_callback_finishing_late(
    model_env,
    monkeypatch,
    phase,
):
    from agent_core.domain.coverage_contracts import CoverageRefusedError
    from agent_storage.postgres import coverage_model_checkpoint as module

    env = model_env(runtime=2)
    request = reserve(env)
    spend(env, request)
    receipt = publish_checkpoint(env, request)
    policy = env.store.model_budget_state(env.binding).policy
    if phase in {"replay", "reservation_replay", "reservation_callback_late"}:
        settle(env, receipt)

    def expire():
        with psycopg.connect(env.dsn) as connection:
            connection.execute(
                "SELECT pg_sleep(greatest(0,extract(epoch FROM "
                "(%s::timestamptz-clock_timestamp())))+0.05)",
                (policy.deadline,),
            )

    if phase in {"callback_late", "reservation_callback_late"}:
        original = module.read_verified_artifact

        def slow_read(*args):
            data = original(*args)
            expire()
            return data

        monkeypatch.setattr(module, "read_verified_artifact", slow_read)
    else:
        expire()
    before, balance = source_counts(env), ledger(env)
    with pytest.raises(CoverageRefusedError):
        if phase.startswith("reservation_"):
            spend(env, request)
        else:
            settle(env, receipt)
    assert ledger(env) == balance and source_counts(env) == before


@pytest.mark.parametrize(
    "gate",
    ["settle", "issue", "retry", "read", "rebuild", "new_reservation", "uncertified_rebuild"],
)
def test_payload_lifecycle_lock_remains_held_through_gate(model_env, proof_env, monkeypatch, gate):  # noqa: F811
    from agent_storage.postgres import coverage_model_checkpoint as module

    if gate in {"issue", "retry", "read", "rebuild"}:
        env = proof_env()
        if gate != "issue":
            _certify(env)
    else:
        env = model_env()
        request = reserve(env)
        spend(env, request)
        receipt = publish_checkpoint(env, request)
        if gate != "settle":
            settle(env, receipt)
    original = module.read_verified_artifact
    entered, release = Event(), Event()

    def read(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    def gate_call():
        if gate == "settle":
            return settle(env, receipt)
        if gate == "new_reservation":
            return spend(env, request.model_copy(update={"reservation_key": "next"}))
        if gate in {"issue", "retry"}:
            return _certify(env)
        if gate == "read":
            return _read(env)
        return env.store.rebuild(env.binding.namespace, env.binding.run_id)

    monkeypatch.setattr(module, "read_verified_artifact", read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(gate_call)
        try:
            assert entered.wait(10)
            with psycopg.connect(env.dsn) as connection:
                connection.execute("SET LOCAL lock_timeout='150ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    connection.execute(
                        "UPDATE artifact_payload_metadata SET retained_until="
                        "request_created_at WHERE artifact_id=%s",
                        (env.checkpoint.artifact_id,),
                    )
        finally:
            release.set()
        # Truthful v2 certification rereads all originals/observations after release;
        # this is a harness wait bound, not execution or retention authority.
        assert future.result(timeout=60) is not None


def model_projections(env):
    with psycopg.connect(env.dsn) as connection:
        return tuple(
            connection.execute(
                f"SELECT to_jsonb(t) FROM {table} t WHERE run_id=%s ORDER BY to_jsonb(t)::text",
                (env.binding.run_id,),
            ).fetchall()
            for table in (
                "coverage_runs",
                "coverage_units",
                "coverage_model_ledger",
                "coverage_model_calls",
                "coverage_model_events",
                "coverage_continuations",
            )
        )


@pytest.mark.parametrize("evidence", ["missing_object", "bytes", "expired"])
@pytest.mark.parametrize("delete_projections", [False, True])
def test_uncertified_rebuild_cannot_restore_refunds_or_new_invocation_authority(
    model_env,
    evidence,
    delete_projections,
):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    retained_until = (
        datetime.now(UTC) + timedelta(seconds=3)
        if evidence == "expired"
        else env.binding.snapshot.expires_at
    )
    settle(env, publish_checkpoint(env, request, retained_until=retained_until))
    assert ledger(env) == (1, 10, 0)
    if evidence == "expired":
        with psycopg.connect(env.dsn) as connection:
            original = connection.execute(
                "SELECT to_jsonb(t) FROM artifact_payload_metadata t WHERE artifact_id=%s",
                (env.checkpoint.artifact_id,),
            ).fetchone()
            connection.execute(
                "SELECT pg_sleep(greatest(0,extract(epoch FROM "
                "(%s::timestamptz-clock_timestamp())))+0.05)",
                (retained_until,),
            )
            assert (
                connection.execute(
                    "SELECT to_jsonb(t) FROM artifact_payload_metadata t WHERE artifact_id=%s",
                    (env.checkpoint.artifact_id,),
                ).fetchone()
                == original
            )
    else:
        damage_checkpoint(env, evidence)
    next_call = request.model_copy(update={"reservation_key": "next", "token_bound": 70})
    before, events = model_projections(env), source_counts(env)
    # A failed rebuild is not a prerequisite: native refunded headroom alone
    # must never permit a different transport call after original proof is lost.
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        spend(env, next_call)
    assert model_projections(env) == before and source_counts(env) == events
    if delete_projections:
        with psycopg.connect(env.dsn) as connection:
            for table in (
                "coverage_model_calls",
                "coverage_model_ledger",
                "coverage_model_events",
                "coverage_runs",
            ):
                connection.execute(f"DELETE FROM {table} WHERE run_id=%s", (env.binding.run_id,))
    before = model_projections(env)
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert model_projections(env) == before and source_counts(env) == events
    assert ledger(env) == (None if delete_projections else (1, 10, 0))
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        spend(env, next_call)
    assert model_projections(env) == before and source_counts(env) == events


@pytest.mark.parametrize("rebuild", [False, True])
def test_shared_settled_replay_refuses_absent_reader_before_any_projection_write(
    model_env, rebuild
):
    from agent_storage.postgres.coverage_model_source import replay_model
    from agent_storage.postgres.coverage_transactions import lock_run

    env = model_env()
    request = reserve(env)
    spend(env, request)
    settle(env, publish_checkpoint(env, request))
    before, events = model_projections(env), source_counts(env)
    with pytest.raises(ValueError, match="governed Artifact reader"):
        with env.store._database.connect() as connection:
            lock_run(connection, NAMESPACE, env.binding, None)
            replay_model(connection, NAMESPACE, env.binding, rebuild=rebuild)
    assert model_projections(env) == before and source_counts(env) == events


@pytest.mark.parametrize("reserved", [False, True])
def test_readerless_replay_preserves_original_full_charge_without_receipts(model_env, reserved):
    from agent_storage.postgres.coverage_model_source import replay_model
    from agent_storage.postgres.coverage_transactions import lock_run

    env = model_env()
    request = reserve(env)
    if reserved:
        spend(env, request)
    expected = env.store.model_budget_state(env.binding)
    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, None)
        state, _ = replay_model(connection, NAMESPACE, env.binding, rebuild=True)
    assert state == expected
    assert ledger(env) == ((1, 70, 1) if reserved else (0, 0, 0))


def test_new_invocation_checks_every_settled_checkpoint(model_env):
    env = model_env(calls=3)
    for index in range(2):
        request = reserve(env, key=f"call-{index}")
        spend(env, request)
        settle(env, publish_checkpoint(env, request))
    list(env.client.objects.values())[1]["Body"] = b"corrupt second proof"
    before, events = model_projections(env), source_counts(env)
    with pytest.raises((ValueError, RuntimeError)):
        spend(env, request.model_copy(update={"reservation_key": "next"}))
    assert model_projections(env) == before and source_counts(env) == events
