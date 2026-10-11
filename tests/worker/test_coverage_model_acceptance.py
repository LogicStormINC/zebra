"""Actual scratch PG acceptance; S3, Host and provider transports are fixtures."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import psycopg
import pytest
from agent_core.application.coverage_checks import merge_observations
from agent_core.application.coverage_executor import observation_id
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import CoverageRefusedError, coverage_digest
from agent_core.domain.coverage_execution import CoverageObservation
from agent_core.domain.coverage_model_budget import (
    CoverageModelReservation,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    CoverageModelCheckpoint,
    decode_model_checkpoint,
)
from agent_core.domain.coverage_persistence import (
    canonical_coverage_bytes,
    coverage_manifest_bytes,
    coverage_result_bytes,
)
from agent_core.domain.coverage_report import CoverageReport
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    expected_units,
    manifest_digest,
    result_set_digest,
)
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.modeling import ModelInvocationPolicy, ModelRole, ModelToolChoice
from agent_core.ports.coverage import CoverageCommit
from agent_integrations.coverage_model_completion import encode_model_completion
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres import coverage as coverage_store
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_model_acceptance import verify_model_results
from agent_storage.postgres.coverage_transactions import lock_run

from tests.agent_integrations.test_coverage_model_invocation import invoke, messages
from tests.agent_storage.test_postgres_command_wakeup import (  # noqa: F401
    NAMESPACE,
    dsn,
    postgres_dsn,
)
from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    CAPACITY,
    check_authority,
    compose,
    model_cloud,
)
from tests.worker.test_coverage_model_cloud import database_state, private_artifact


def configured(env, derive=derive_semantic_observation):
    env.store = PostgresCoverageStore(
        env.dsn,
        deployment_namespace=NAMESPACE,
        artifacts=env.cloud,
        supported_model_profiles=(env.admission.model_profile,),
        model_observation_deriver=derive,
    )


def settled(env):
    invoke(env, compose(env))
    configured(env)
    identifier, body = private_artifact(env, MODEL_CHECKPOINT_KIND)
    receipt = CoverageModelUsageReceipt.model_validate(database_state(env)[1][0][1])
    observation = derive_semantic_observation(body, receipt, env.definition, env.key, env.record)
    return observation, identifier


def publish(env, identifier, kind, body):
    return env.cloud.store_payload_immutable(
        ArtifactPayloadWrite(
            session_id=env.session,
            kind=kind,
            mime_type="application/octet-stream",
            payload=body,
            created_at=datetime.now(UTC),
            retained_until=env.binding.snapshot.expires_at,
        ),
        artifact_id=identifier,
    ).uri


def request_for(env, observation, *, supplied=None):
    publish(
        env,
        observation_id(env.binding, observation.key),
        "coverage_observation",
        canonical_coverage_bytes(observation.model_dump(mode="json")),
    )
    result = supplied or AcceptedCoverageUnit(
        key=observation.key, result_digest=observation.digest, outcome=observation.outcome
    )
    body = coverage_result_bytes((result,))
    digest = sha256(body).hexdigest()
    identifier = ArtifactId(uuid5(NAMESPACE_URL, "acceptance-batch:" + digest))
    ref = publish(env, identifier, "coverage_results", body)
    return CoverageCommit(
        namespace=env.binding.namespace,
        session_id=env.session,
        task_id=env.binding.task_id,
        run_id=env.binding.run_id,
        snapshot_id=env.binding.snapshot.snapshot_id,
        contract_digest=env.binding.contract.digest,
        manifest_digest=env.binding.snapshot.manifest_digest,
        commit_key=str(identifier),
        result_artifact_ref=ref,
        result_artifact_digest=digest,
        results=(result,),
    )


def accepted(env):
    observation, identifier = settled(env)
    request = request_for(env, observation)
    first = env.store.commit(request, fence=env.fence)
    assert env.store.commit(request, fence=env.fence) == first
    key = next(
        k for k in expected_units(env.binding.contract, (env.record,)) if k.kind == "record_merge"
    )
    merge = merge_observations(key, tuple(p.id for p in env.record.parts), (observation,))
    merged_request = request_for(env, merge)
    env.store.commit(merged_request, fence=env.fence)
    return request, observation, merge, identifier


def report_for(env, observations):
    results = tuple(
        item for _, item in env.store.accepted_page(env.binding.namespace, env.binding.run_id)
    )
    report = CoverageReport(
        schema="coverage-report/1",
        binding_digest=coverage_digest(env.binding.model_dump(mode="json")),
        result_set_digest=result_set_digest(results),
        observations=observations,
    )
    body = report.canonical_bytes
    digest = sha256(body).hexdigest()
    ref = publish(
        env,
        ArtifactId(uuid5(NAMESPACE_URL, "acceptance-report:" + digest)),
        "coverage_report",
        body,
    )
    return ref, digest


def certify(env, ref, digest):
    return env.store.certify(
        env.binding.namespace,
        env.binding.run_id,
        report_ref=ref,
        report_digest=digest,
        fence=env.fence,
        check_authority=lambda: check_authority(env),
    )


def history(env):
    # Never include DSN or connection repr in assertion payloads.
    return env.events.list_for_session(env.session)


def test_derived_commit_retry_rebuild_certify_read_without_more_http(model_cloud):  # noqa: F811
    env = model_cloud
    request, observation, merge, _ = accepted(env)
    before = history(env)
    env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert history(env) == before and env.store.counts(
        env.binding.namespace, env.binding.run_id
    ) == (2, 2)
    ref, digest = report_for(env, (observation, merge))
    certificate = certify(env, ref, digest)
    before, budget = history(env), database_state(env)
    assert certify(env, ref, digest) == certificate
    assert env.store.commit(request, fence=env.fence).event_watermark < certificate.event_watermark
    assert env.store.certificate(
        env.binding.namespace,
        env.binding.run_id,
        now=datetime.now(UTC),
        check_authority=lambda: check_authority(env),
    ) == (certificate, ref)
    env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert history(env) == before and database_state(env) == budget and len(env.requests) == 1


@pytest.mark.parametrize(
    "defect",
    [
        "digest",
        "outcome",
        "observation",
        "missing_verifier",
        "unknown_receipt",
        "checkpoint",
        "source_event",
        "ledger",
        "materialized",
        "unsettled",
    ],
)
def test_strict_forgery_refuses_without_acceptance_or_budget_change(model_cloud, defect):  # noqa: F811
    env = model_cloud
    observation, identifier = settled(env)
    supplied = None
    if defect == "digest":
        supplied = AcceptedCoverageUnit(
            key=observation.key, result_digest="f" * 64, outcome="clear"
        )
    elif defect == "outcome":
        supplied = AcceptedCoverageUnit(
            key=observation.key, result_digest=observation.digest, outcome="finding"
        )
    elif defect == "observation":
        observation = observation.model_copy(update={"summary": "forged same key"})
    request = request_for(env, observation, supplied=supplied)
    if defect == "missing_verifier":
        configured(env, None)
    elif defect in {"checkpoint", "materialized"}:
        if defect == "checkpoint":
            digest = env.cloud.get_payload(identifier).sha256
            for value in env.client.objects.values():
                if sha256(value["Body"]).hexdigest() == digest:
                    value["Body"] = b"tampered original"
        else:
            with psycopg.connect(env.dsn) as connection:
                connection.execute(
                    "UPDATE session_events SET payload=jsonb_set(payload,'{sha256}',"
                    "to_jsonb(%s::text)) WHERE event_type='coverage_artifact_materialized' "
                    "AND payload->'metadata'->>'artifact_uri'=%s",
                    ("a" * 64, f"artifact://{observation_id(env.binding, env.key)}"),
                )
    elif defect in {"unknown_receipt", "source_event", "ledger", "unsettled"}:
        with psycopg.connect(env.dsn) as connection:
            if defect == "unknown_receipt":
                connection.execute(
                    "DELETE FROM coverage_model_calls WHERE run_id=%s", (env.binding.run_id,)
                )
            elif defect == "source_event":
                connection.execute(
                    "UPDATE session_events SET payload=jsonb_set(payload,'{receipt,total_tokens}',"
                    "'31') WHERE session_id=%s AND event_type='coverage_model_usage_recorded'",
                    (env.session,),
                )
            elif defect == "ledger":
                connection.execute(
                    "UPDATE coverage_model_ledger SET charged_tokens=0 WHERE run_id=%s",
                    (env.binding.run_id,),
                )
            else:
                connection.execute(
                    "UPDATE coverage_model_calls SET receipt=NULL,receipt_sequence=NULL "
                    "WHERE run_id=%s",
                    (env.binding.run_id,),
                )
    before, events = database_state(env), history(env)
    with pytest.raises((ValueError, RuntimeError, CoverageRefusedError)):
        env.store.commit(request, fence=env.fence)
    assert database_state(env) == before and history(env) == events
    assert (
        env.store.counts(env.binding.namespace, env.binding.run_id) == (2, 0)
        and len(env.requests) == 1
    )


@pytest.mark.parametrize("gate", ["retry", "rebuild", "certify", "certificate"])
def test_current_original_tamper_refuses_every_gate(model_cloud, gate):  # noqa: F811
    env = model_cloud
    request, observation, merge, identifier = accepted(env)
    ref, digest = report_for(env, (observation, merge))
    if gate == "certificate":
        certify(env, ref, digest)
    digest_original = env.cloud.get_payload(identifier).sha256
    for value in env.client.objects.values():
        if sha256(value["Body"]).hexdigest() == digest_original:
            value["Body"] = b"tamper"
    before, events = database_state(env), history(env)
    with pytest.raises((ValueError, RuntimeError, CoverageRefusedError)):
        if gate == "retry":
            env.store.commit(request, fence=env.fence)
        elif gate == "rebuild":
            env.store.rebuild(env.binding.namespace, env.binding.run_id)
        elif gate == "certify":
            certify(env, ref, digest)
        else:
            env.store.certificate(
                env.binding.namespace,
                env.binding.run_id,
                now=datetime.now(UTC),
                check_authority=lambda: check_authority(env),
            )
    assert database_state(env) == before and history(env) == events and len(env.requests) == 1


@pytest.mark.parametrize("defect", ["v1", "source", "wire", "request", "identity", "unresolved"])
def test_accounted_original_is_insufficient_for_semantic_acceptance(model_cloud, defect):  # noqa: F811
    env = model_cloud
    compose(env)
    configured(env)
    gateway = env.factory()
    prepared = gateway.prepare_text_request(
        messages(env),
        invocation_policy=ModelInvocationPolicy(
            role=ModelRole.REVIEWER,
            profile_id=env.admission.model_profile,
            tool_choice=ModelToolChoice.NONE,
            max_output_tokens=8192,
        ),
    )
    wire = json.loads(prepared.body)
    if defect == "source":
        payload = json.loads(wire["messages"][1]["content"])
        payload["bodies"][env.key.part_id] = "forged source"
        wire["messages"][1]["content"] = json.dumps(payload)
    elif defect == "wire":
        wire["thinking"] = {"type": "disabled"}
    elif defect == "request":
        wire["messages"][0]["content"] = "changed frozen instructions"
    original_request = canonical_coverage_bytes(wire)
    reservation = CoverageModelReservation(
        reservation_key="lower-layer-original",
        admission_digest=env.policy.admission_digest,
        key=env.key,
        request_digest=sha256(original_request).hexdigest(),
        model_profile=env.admission.model_profile,
        token_bound=CAPACITY,
    )
    env.store.reserve_model_call(env.binding, reservation, fence=env.fence)
    response = gateway.complete_prepared(prepared)
    metadata = replace(response.call_metadata, request_hash=reservation.request_digest)
    if defect == "identity":
        metadata = replace(metadata, provider="foreign")
    if defect == "unresolved":
        content = json.loads(response.assistant_message.content)
        content["outcome"] = "unresolved"
        response = replace(
            response,
            assistant_message=response.assistant_message.model_copy(
                update={"content": json.dumps(content)}
            ),
        )
    response = replace(response, call_metadata=metadata)
    checkpoint = CoverageModelCheckpoint(
        env.binding,
        reservation,
        encode_model_completion(response),
        None if defect == "v1" else original_request,
    )
    env.cloud.store_payload_immutable(
        ArtifactPayloadWrite(
            session_id=env.session,
            kind=MODEL_CHECKPOINT_KIND,
            mime_type="application/json",
            payload=checkpoint.canonical_bytes,
            created_at=datetime.now(UTC),
            retained_until=env.binding.snapshot.expires_at,
        ),
        artifact_id=checkpoint.artifact_id,
    )
    receipt = CoverageModelUsageReceipt(
        reservation=reservation,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        checkpoint_ref=f"artifact://{checkpoint.artifact_id}",
        checkpoint_digest=checkpoint.digest,
    )
    env.store.record_model_usage(env.binding, receipt, fence=env.fence)
    assert database_state(env)[0] == (1, 30, 0)  # Genuine settled accounting still succeeds.
    observation = CoverageObservation(
        key=env.key, outcome="clear", summary="Bounded semantic source annotation: clear"
    )
    request = request_for(env, observation)
    before, events = database_state(env), history(env)
    with pytest.raises((ValueError, CoverageRefusedError)):
        env.store.commit(request, fence=env.fence)
    assert database_state(env) == before and history(env) == events and len(env.requests) == 1


@pytest.mark.parametrize("defect", ["extra", "nested_extra", "nested_type", "wrong_key"])
def test_configured_deriver_raw_return_is_validated(model_cloud, defect):  # noqa: F811
    env = model_cloud
    observation, _ = settled(env)
    request = request_for(env, observation)

    def bad_deriver(*args):
        result = derive_semantic_observation(*args)
        if defect == "extra":
            result.__dict__["illicit"] = True
        elif defect == "nested_extra":
            result.key.__dict__["illicit"] = True
        elif defect == "nested_type":
            result.key.__dict__["part_id"] = False
        else:
            result = result.model_copy(
                update={"key": result.key.model_copy(update={"record_id": "foreign"})}
            )
        return result

    configured(env, bad_deriver)
    before, events = database_state(env), history(env)
    with pytest.raises(ValueError):
        env.store.commit(request, fence=env.fence)
    assert database_state(env) == before and history(env) == events and len(env.requests) == 1


@pytest.mark.parametrize("model_cloud", [60], indirect=True)
def test_issued_certificate_reads_after_original_deadline(model_cloud):  # noqa: F811
    env = model_cloud
    _, observation, merge, _ = accepted(env)
    ref, digest = report_for(env, (observation, merge))
    certificate = certify(env, ref, digest)
    before, budget = history(env), database_state(env)
    with psycopg.connect(env.dsn) as connection:
        connection.execute(
            "SELECT pg_sleep(greatest(0,extract(epoch FROM "
            "(%s::timestamptz-clock_timestamp())))+0.03)",
            (env.policy.deadline,),
        )
    assert datetime.now(UTC) >= env.policy.deadline
    assert env.store.certificate(
        env.binding.namespace,
        env.binding.run_id,
        now=datetime.now(UTC),
        check_authority=lambda: check_authority(env),
    ) == (certificate, ref)
    assert certify(env, ref, digest) == certificate
    env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert history(env) == before and database_state(env) == budget and len(env.requests) == 1


@pytest.mark.parametrize("defect", ["missing", "digests", "outcome", "quotes"])
def test_merge_requires_all_original_derived_parts(model_cloud, defect):  # noqa: F811
    env = model_cloud
    observation, _ = settled(env)
    if defect != "missing":
        env.store.commit(request_for(env, observation), fence=env.fence)
    key = next(
        k for k in expected_units(env.binding.contract, (env.record,)) if k.kind == "record_merge"
    )
    merge = merge_observations(key, tuple(p.id for p in env.record.parts), (observation,))
    if defect == "digests":
        merge = merge.model_copy(update={"part_result_digests": ("a" * 64,)})
    elif defect == "outcome":
        merge = merge.model_copy(update={"outcome": "finding"})
        # Keep a valid forged shape so the derivation gate, not raw validation, refuses it.
        from agent_core.domain.coverage_execution import CoverageQuote

        merge = merge.model_copy(
            update={
                "quotes": (CoverageQuote(part_id=env.key.part_id, start=0, end=6, text="source"),)
            }
        )
    elif defect == "quotes":
        merge = merge.model_copy(update={"summary": "forged merged narration"})
    request = request_for(env, merge)
    before, events = database_state(env), history(env)
    with pytest.raises(ValueError):
        env.store.commit(request, fence=env.fence)
    assert database_state(env) == before and history(env) == events and len(env.requests) == 1


@pytest.fixture
def multipart_cloud(model_cloud):  # noqa: F811
    env = model_cloud
    compose(env)
    # Host v1 admits one canonical_body. Exercise multipart at the Core/native
    # manifest boundary with explicit fixture data, not a claim about Host v1.
    env.record = env.record.model_copy(
        update={
            "parts": (
                env.record.parts[0],
                env.record.parts[0].model_copy(update={"id": "second_canonical"}),
            )
        }
    )
    body = coverage_manifest_bytes((env.record,))
    identifier = ArtifactId(uuid5(NAMESPACE_URL, "multipart-manifest:" + str(env.session)))
    snapshot = env.binding.snapshot.model_copy(
        update={
            "manifest_artifact_ref": f"artifact://{identifier}",
            "manifest_digest": manifest_digest(env.binding.contract, (env.record,)),
        }
    )
    env.binding = env.binding.model_copy(
        update={
            "run_id": env.binding.run_id + ":multipart",
            "snapshot": snapshot,
            "manifest_artifact_digest": sha256(body).hexdigest(),
        }
    )
    env.cloud.binding = env.binding
    publish(env, identifier, "coverage_manifest", body)
    configured(env)
    env.store.bind(env.binding, fence=env.fence)
    return env


@pytest.mark.parametrize("reverse", [False, True])
def test_multipart_settled_originals_bind_canonical_order_and_quotes(multipart_cloud, reverse):
    env = multipart_cloud
    invocation = compose(env)
    observations = []
    keys = expected_units(env.binding.contract, (env.record,))
    for key in (key for key in keys if key.kind == "part"):
        env.key = key
        finding = key.part_id == env.record.parts[0].id
        env.reply["choices"][0]["message"]["content"] = json.dumps(
            {
                "key": key.model_dump(mode="json"),
                "outcome": "finding" if finding else "clear",
                "categories": ["explicit_operational_or_harm_claim"] if finding else [],
                "quotes": [{"part_id": key.part_id, "start": 0, "end": 6, "text": "source"}]
                if finding
                else [],
            }
        )
        invoke(env, invocation)
        configured(env)
        receipt = next(
            CoverageModelUsageReceipt.model_validate(row[1])
            for row in database_state(env)[1]
            if CoverageModelUsageReceipt.model_validate(row[1]).reservation.key == key
        )
        from uuid import UUID

        original = env.cloud.read_payload_bytes(
            ArtifactId(UUID(receipt.checkpoint_ref.removeprefix("artifact://")))
        )
        observation = derive_semantic_observation(
            original, receipt, env.definition, key, env.record
        )
        env.store.commit(request_for(env, observation), fence=env.fence)
        observations.append(observation)
    merge = merge_observations(keys[-1], tuple(p.id for p in env.record.parts), tuple(observations))
    assert merge.outcome == "finding" and merge.quotes == observations[0].quotes
    if reverse:
        merge = merge.model_copy(
            update={"part_result_digests": tuple(reversed(merge.part_result_digests))}
        )
    request = request_for(env, merge)
    before, events = database_state(env), history(env)
    if reverse:
        with pytest.raises(ValueError):
            env.store.commit(request, fence=env.fence)
        assert database_state(env) == before and history(env) == events
    else:
        env.store.commit(request, fence=env.fence)
        ref, digest = report_for(env, (*observations, merge))
        certify(env, ref, digest)
        env.store.rebuild(env.binding.namespace, env.binding.run_id)
        assert env.store.counts(env.binding.namespace, env.binding.run_id) == (3, 3)
    assert database_state(env)[0] == (2, 60, 0) and len(env.requests) == 2


@pytest.mark.parametrize("kind", ["coverage_observation", "coverage_results"])
def test_final_native_clock_preserves_earliest_observation_and_batch_retention(
    model_cloud,  # noqa: F811
    monkeypatch,
    kind,
):
    env = model_cloud
    observation, _ = settled(env)
    deadline = datetime.now(UTC) + timedelta(seconds=15)
    original_publish = env.cloud.store_payload_immutable

    def publish_with_deadline(payload, *, artifact_id):
        if payload.kind == kind:
            payload = payload.model_copy(update={"retained_until": deadline})
        return original_publish(payload, artifact_id=artifact_id)

    monkeypatch.setattr(env.cloud, "store_payload_immutable", publish_with_deadline)
    request = request_for(env, observation)
    original_validate = coverage_store.validate_write
    reached = False

    def delay_final_validation(connection, *args, **kwargs):
        nonlocal reached
        value = original_validate(connection, *args, **kwargs)
        reached = True
        connection.execute(
            "SELECT pg_sleep(greatest(0,extract(epoch FROM "
            "(%s::timestamptz-clock_timestamp())))+0.03)",
            (deadline,),
        )
        return value

    monkeypatch.setattr(coverage_store, "validate_write", delay_final_validation)
    before, events = database_state(env), history(env)
    with pytest.raises(ValueError, match="retention"):
        env.store.commit(request, fence=env.fence)
    assert reached and database_state(env) == before and history(env) == events
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (2, 0)


def test_duplicate_settled_originals_do_not_prove_one_semantic_part(model_cloud):  # noqa: F811
    env = model_cloud
    observation, _ = settled(env)
    receipt = CoverageModelUsageReceipt.model_validate(database_state(env)[1][0][1])
    original = decode_model_checkpoint(private_artifact(env, MODEL_CHECKPOINT_KIND)[1])
    reservation = receipt.reservation.model_copy(update={"reservation_key": "duplicate-original"})
    env.store.reserve_model_call(env.binding, reservation, fence=env.fence)
    duplicate = CoverageModelCheckpoint(
        env.binding, reservation, original.completion, original.request
    )
    env.cloud.store_payload_immutable(
        ArtifactPayloadWrite(
            session_id=env.session,
            kind=MODEL_CHECKPOINT_KIND,
            mime_type="application/json",
            payload=duplicate.canonical_bytes,
            created_at=datetime.now(UTC),
            retained_until=env.binding.snapshot.expires_at,
        ),
        artifact_id=duplicate.artifact_id,
    )
    env.store.record_model_usage(
        env.binding,
        receipt.model_copy(
            update={
                "reservation": reservation,
                "checkpoint_ref": f"artifact://{duplicate.artifact_id}",
                "checkpoint_digest": duplicate.digest,
            }
        ),
        fence=env.fence,
    )
    request = request_for(env, observation)
    before, events = database_state(env), history(env)
    assert before[0] == (2, 60, 0)
    with pytest.raises(ValueError, match="duplicate settled receipts"):
        env.store.commit(request, fence=env.fence)
    assert database_state(env) == before and history(env) == events and len(env.requests) == 1


@pytest.mark.parametrize("model_cloud", [30], indirect=True)
def test_original_native_deadline_refuses_first_unit_acceptance(model_cloud):  # noqa: F811
    env = model_cloud
    observation, _ = settled(env)
    request = request_for(env, observation)
    before, events = database_state(env), history(env)
    with psycopg.connect(env.dsn) as connection:
        connection.execute(
            "SELECT pg_sleep(greatest(0,extract(epoch FROM "
            "(%s::timestamptz-clock_timestamp())))+0.03)",
            (env.policy.deadline,),
        )
    with pytest.raises(ValueError, match="original execution deadline"):
        env.store.commit(request, fence=env.fence)
    assert database_state(env) == before and history(env) == events and len(env.requests) == 1


def test_missing_admission_cannot_downgrade_existing_native_model_proof(model_cloud):  # noqa: F811
    env = model_cloud
    settled(env)
    with psycopg.connect(env.dsn) as connection:
        connection.execute(
            "UPDATE session_events SET payload=jsonb_set(payload,'{coverage_admission}','null') "
            "WHERE session_id=%s AND event_type='task_prepared'",
            (env.session,),
        )
    before, events = database_state(env), history(env)
    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, env.fence)
        with pytest.raises(ValueError, match="admitted manifest"):
            verify_model_results(
                connection,
                NAMESPACE,
                env.binding,
                (),
                artifacts=env.cloud,
                derive=derive_semantic_observation,
                deadlines=[],
            )
    assert database_state(env) == before and history(env) == events and len(env.requests) == 1
