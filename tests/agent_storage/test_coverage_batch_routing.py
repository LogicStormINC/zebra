"""Record routing skips unrelated objects, never independent certification."""

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectNotFoundError
from agent_core.domain.events import EventType
from agent_storage.postgres.coverage_model_verification import _ModelVerification
from agent_storage.postgres.coverage_projection import replay_request
from agent_storage.postgres.coverage_transactions import lock_run

from tests.agent_storage.test_coverage_model_verification_native import two_records
from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.coverage_model_cloud_fixtures import NAMESPACE, model_cloud  # noqa: F401


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("legacy", [False, True])
def test_incremental_batches_are_record_scoped_but_final_scan_is_complete(
    model_cloud, legacy, monkeypatch,  # noqa: F811
):
    env = two_records(model_cloud)
    events = [e for e in env.events.list_for_session(env.session)
              if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED]
    request = replay_request(env.artifacts, env.binding, events[-1])
    if legacy:
        with env.store._database.connect() as connection:
            connection.execute(
                "UPDATE session_events SET payload=payload-'record_ids' "
                "WHERE deployment_namespace=%s AND session_id=%s "
                "AND event_type='coverage_batch_accepted'",
                (NAMESPACE, env.session),
            )
    import agent_storage.postgres.coverage_model_verification as verification

    reads = []
    original = verification.replay_request

    def replay(*args):
        reads.append(args[-1].event_id)
        return original(*args)

    monkeypatch.setattr(verification, "replay_request", replay)
    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, None)
        kwargs = dict(artifacts=env.artifacts, derive=env.store._model_observation_deriver)
        scoped = _ModelVerification(
            connection, NAMESPACE, env.binding, _commit_results=request.results, **kwargs,
        )
        assert len(scoped.batches()) == (4 if legacy else 2)
        assert len(reads) == (4 if legacy else 2)
        reads.clear()
        full = _ModelVerification(connection, NAMESPACE, env.binding, **kwargs)
        assert len(full.batches()) == len(reads) == 4


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("selected", [False, True])
def test_result_object_damage_keeps_selected_proof_and_final_gate(model_cloud, selected):  # noqa: F811
    env = two_records(model_cloud)
    events = [e for e in env.events.list_for_session(env.session)
              if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED]
    request = replay_request(env.artifacts, env.binding, events[-1])
    from hashlib import sha256

    digest = events[2 if selected else 0].payload["request"]["result_artifact_digest"]
    key = next(k for k, value in env.client.objects.items()
               if sha256(value["Body"]).hexdigest() == digest)
    del env.client.objects[key]
    if selected:
        with pytest.raises(ArtifactObjectNotFoundError):
            env.store.commit(request, fence=env.fence)
    else:
        receipt = env.store.commit(request, fence=env.fence)
        assert receipt.event_watermark == events[-1].sequence
    with pytest.raises(ArtifactObjectNotFoundError):
        env.store.certify(
            env.binding.namespace, env.binding.run_id,
            report_ref=env.report_artifact.uri, report_digest=env.report_artifact.sha256,
            fence=env.fence, check_authority=lambda: None,
        )


@pytest.mark.parametrize("record_ids", [[], ["wrong"], None, ["second_record", "wrong"]])
def test_routing_hint_must_match_canonical_batch(model_cloud, record_ids):  # noqa: F811
    env = two_records(model_cloud)
    event = next(e for e in reversed(env.events.list_for_session(env.session))
                 if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED)
    changed = event.model_copy(update={"payload": {**event.payload, "record_ids": record_ids}})
    with pytest.raises(ValueError, match="disagrees with immutable Artifact"):
        replay_request(env.artifacts, env.binding, changed)


def test_oversized_optional_hint_preserves_existing_payload_bound(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from agent_storage.postgres import coverage_transactions as transactions

    from tests.agent_core.test_coverage_persistence import binding

    monkeypatch.setattr(transactions, "validate_write", lambda *a, **k:
                        (datetime.now(UTC), "digest", 1))
    monkeypatch.setattr(transactions, "append_event_in_transaction", lambda c, d, e: e)
    event = transactions.append_coverage_event(
        None, "deployment", binding(), SimpleNamespace(model_dump=lambda **k: {}), 1,
        EventType.COVERAGE_BATCH_ACCEPTED,
        {"request": {}, "record_ids": [f"{i}:" + "x" * 256 for i in range(1000)]},
    )
    assert "record_ids" not in event.payload
    with pytest.raises(ValueError, match="bounded payload limit"):
        transactions.append_coverage_event(
            None, "deployment", binding(), SimpleNamespace(model_dump=lambda **k: {}), 1,
            EventType.COVERAGE_BATCH_ACCEPTED, {"request": "x" * 65536},
        )


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_hint_hiding_required_part_cannot_accept_merge(model_cloud):  # noqa: F811
    from psycopg.types.json import Jsonb

    env = two_records(model_cloud)
    events = [e for e in env.events.list_for_session(env.session)
              if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED]
    request = replay_request(env.artifacts, env.binding, events[-1])
    with env.store._database.connect() as connection:
        connection.execute(
            "UPDATE session_events SET payload=jsonb_set(payload,'{record_ids}',%s) "
            "WHERE deployment_namespace=%s AND event_id=%s",
            (Jsonb(["unrelated"]), NAMESPACE, events[-2].event_id),
        )
    with pytest.raises(ValueError, match="part"):
        env.store.commit(request, fence=env.fence)
    with pytest.raises(ValueError, match="disagrees with immutable Artifact"):
        env.store.certify(
            env.binding.namespace, env.binding.run_id,
            report_ref=env.report_artifact.uri, report_digest=env.report_artifact.sha256,
            fence=env.fence, check_authority=lambda: None,
        )


def test_mixed_record_batch_hint_binds_all_results(model_cloud):  # noqa: F811
    from hashlib import sha256
    from uuid import NAMESPACE_URL, uuid5

    from agent_core.domain.coverage_persistence import coverage_result_bytes
    from agent_core.domain.identifiers import ArtifactId
    from agent_storage.postgres.coverage_transactions import request_digest
    from psycopg.types.json import Jsonb

    from tests.worker.test_coverage_model_acceptance import publish

    env = two_records(model_cloud)
    events = [e for e in env.events.list_for_session(env.session)
              if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED]
    requests = [replay_request(env.artifacts, env.binding, e) for e in events[::2]]
    results = tuple(item for request in requests for item in request.results)
    body = coverage_result_bytes(results)
    digest = sha256(body).hexdigest()
    ref = publish(env, ArtifactId(uuid5(NAMESPACE_URL, digest)), "coverage_results", body)
    request = requests[0].model_copy(update={
        "results": results, "result_artifact_ref": ref, "result_artifact_digest": digest,
    })
    payload = {**events[0].payload, "request": request.model_dump(mode="json", exclude={"results"}),
               "request_digest": request_digest(request), "result_count": 2,
               "record_ids": sorted({item.key.record_id for item in results})}
    event = events[0].model_copy(update={"payload": payload})
    assert replay_request(env.artifacts, env.binding, event) == request
    with env.store._database.connect() as connection:
        connection.execute(
            "UPDATE session_events SET payload=%s WHERE deployment_namespace=%s AND event_id=%s",
            (Jsonb(payload), NAMESPACE, event.event_id),
        )
    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, None)
        transcript = _ModelVerification(
            connection, NAMESPACE, env.binding, artifacts=env.artifacts,
            derive=env.store._model_observation_deriver,
        )
        transcript._batch_record_ids = [results[-1].key.record_id]
        # Mixed source must be selected and read whole. The original second part
        # still exists in this tampered fixture, so duplicate detection must fire.
        with pytest.raises(ValueError, match="duplicate source Artifacts"):
            transcript.batches()
        assert set(transcript.part_sources) == {item.key.record_id for item in results}
