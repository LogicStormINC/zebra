"""Real multipart acceptance/proof and certificates; transport objects are fixtures."""

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from agent_core.application.coverage_checks import merge_observations
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_core.domain.coverage_persistence import coverage_manifest_bytes
from agent_core.domain.coverage_validation import expected_units, manifest_digest
from agent_core.domain.identifiers import ArtifactId
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres import coverage_model_acceptance as acceptance
from agent_storage.postgres import coverage_model_source as source
from agent_storage.postgres import coverage_model_verification as verification
from agent_storage.postgres.coverage_model_verification import _ModelVerification
from agent_storage.postgres.coverage_transactions import lock_run

from tests.agent_integrations.test_coverage_model_invocation import invoke
from tests.agent_storage.coverage_model_proof_fixtures import proof_env  # noqa: F401
from tests.agent_storage.test_postgres_command_wakeup import (  # noqa: F401
    NAMESPACE,
    dsn,
    postgres_dsn,
)
from tests.worker.coverage_model_cloud_fixtures import compose, model_cloud  # noqa: F401
from tests.worker.test_coverage_model_acceptance import configured, publish, report_for, request_for
from tests.worker.test_coverage_model_cloud import database_state


def two_records(env):
    compose(env)
    records = (
        env.record,
        env.record.model_copy(update={"record_id": "second_record", "ordinal": 1}),
    )
    body = coverage_manifest_bytes(records)
    identifier = ArtifactId(uuid5(NAMESPACE_URL, "two-records:" + str(env.session)))
    env.binding = env.binding.model_copy(
        update={
            "run_id": env.binding.run_id + ":two-records",
            "snapshot": env.binding.snapshot.model_copy(
                update={
                    "record_count": len(records),
                    "manifest_artifact_ref": f"artifact://{identifier}",
                    "manifest_digest": manifest_digest(env.binding.contract, records),
                }
            ),
            "manifest_artifact_digest": sha256(body).hexdigest(),
        }
    )
    env.cloud.binding = env.binding
    publish(env, identifier, "coverage_manifest", body)
    configured(env)
    env.store.bind(env.binding, fence=env.fence)
    component = compose(env)
    observations = []
    for record in records:
        env.record = record
        keys = expected_units(env.binding.contract, (record,))
        env.key = keys[0]
        env.reply["choices"][0]["message"]["content"] = json.dumps(
            {
                "key": env.key.model_dump(mode="json"),
                "outcome": "clear",
                "categories": [],
                "quotes": [],
            }
        )
        invoke(env, component)
        configured(env)
        receipt = next(
            CoverageModelUsageReceipt.model_validate(row[1])
            for row in database_state(env)[1]
            if CoverageModelUsageReceipt.model_validate(row[1]).reservation.key == env.key
        )
        original = env.cloud.read_payload_bytes(
            ArtifactId(UUID(receipt.checkpoint_ref.removeprefix("artifact://")))
        )
        part = derive_semantic_observation(original, receipt, env.definition, env.key, record)
        env.store.commit(request_for(env, part), fence=env.fence)
        merged = merge_observations(keys[-1], tuple(p.id for p in record.parts), (part,))
        env.store.commit(request_for(env, merged), fence=env.fence)
        observations.extend((part, merged))
    ref, digest = report_for(env, tuple(observations))
    env.report_artifact = SimpleNamespace(uri=ref, sha256=digest)
    env.artifacts = env.cloud
    return env


@pytest.mark.parametrize("record_count", [1, 2])
def test_native_multipart_phase_counts_sequence_and_original_certificate(
    request,
    monkeypatch,
    record_count,
):
    env = (
        request.getfixturevalue("proof_env")(multipart=True)
        if record_count == 1
        else two_records(request.getfixturevalue("model_cloud"))
    )
    counts = Counter()
    original_read = env.artifacts.objects.read_version_verified

    def read_original(expectation, version):
        if env.artifacts.get_payload(expectation.artifact_id).kind == MODEL_CHECKPOINT_KIND:
            counts["physical_original"] += 1
        return original_read(expectation, version)

    monkeypatch.setattr(env.artifacts.objects, "read_version_verified", read_original)

    def count(module, name, counter):
        original = getattr(module, name)

        def wrapped(*args, **kwargs):
            counts[counter] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapped)

    count(verification, "read_manifest", "manifest")
    count(verification, "replay_model", "ledger")
    count(verification, "replay_request", "batch")
    count(acceptance, "verify_results", "request")
    count(source, "verify_model_checkpoint", "ledger_checkpoint")
    count(acceptance, "verify_model_checkpoint", "part_checkpoint")
    original = env.store._model_observation_deriver

    def derive(*args):
        counts["derive"] += 1
        return original(*args)

    env.store._model_observation_deriver = derive

    class CountedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, *args, **kwargs):
            if "event_type='coverage_batch_accepted'" in sql:
                counts["batch_page"] += 1
            return self.connection.execute(sql, *args, **kwargs)

    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, None)
        accepted = env.store._accepted_results(connection, env.binding)
        env.store._verify_result_sources(CountedConnection(connection), env.binding, accepted)
        assert counts == Counter(
            manifest=1,
            ledger=1,
            batch=2 + record_count,
            request=2 + record_count,
            ledger_checkpoint=2,
            part_checkpoint=4,
            derive=4,
            batch_page=1,  # Short locked page is exhaustive; no empty-page probe.
            physical_original=2,
        )
        transcript = _ModelVerification(
            connection,
            NAMESPACE,
            env.binding,
            artifacts=env.artifacts,
            derive=derive,
        )
        batches = transcript.batches()
        merge = next(item for item in accepted if item.key.kind == "record_merge")
        first_part = next(
            sequence for sequence, batch, _ in batches if batch.results[0].key.kind == "part"
        )
        # Populate the same transcript's source cache first; each call still applies its fence.
        for sequence in (first_part - 1, first_part):
            with pytest.raises(ValueError, match="source missing/conflicting"):
                transcript.verify((merge,), deadlines=[], before_sequence=sequence)
        part = next(item for item in accepted if item.key.kind == "part")
        receipt_sequence = transcript.settled[part.key][0]["receipt_sequence"]
        for sequence in (receipt_sequence - 1, receipt_sequence):
            with pytest.raises(ValueError, match="settlement"):
                transcript.verify((part,), deadlines=[], before_sequence=sequence)
        if record_count == 2:
            merges = tuple(item for item in accepted if item.key.kind == "record_merge")
            proof_bytes = []
            real_pin = acceptance.pin_evidence
            real_checkpoint = acceptance.verify_model_checkpoint

            def charged_pin(*args):
                size = real_pin(*args)
                proof_bytes.append(size)
                return size

            def charged_checkpoint(*args, **kwargs):
                body = real_checkpoint(*args, **kwargs)
                proof_bytes.append(len(body))
                return body

            with monkeypatch.context() as charging:
                charging.setattr(acceptance, "pin_evidence", charged_pin)
                charging.setattr(acceptance, "verify_model_checkpoint", charged_checkpoint)
                individual_sizes = []
                for item in merges:
                    start = len(proof_bytes)
                    transcript.verify((item,), deadlines=[])
                    individual_sizes.append(sum(proof_bytes[start:]))
            exact = transcript.spent + transcript.batch_bytes + individual_sizes[0]
            with monkeypatch.context() as boundary:
                boundary.setattr(acceptance, "MAX_COVERAGE_ARTIFACT_BYTES", exact)
                transcript.verify((merges[0],), deadlines=[])
                boundary.setattr(acceptance, "MAX_COVERAGE_ARTIFACT_BYTES", exact - 1)
                with pytest.raises(ValueError, match="cumulative read bound"):
                    transcript.verify((merges[0],), deadlines=[])
            cap = transcript.spent + transcript.batch_bytes + sum(proof_bytes)
            with monkeypatch.context() as bounded:
                bounded.setattr(acceptance, "MAX_COVERAGE_ARTIFACT_BYTES", cap)
                for _ in range(2):
                    for item in merges:
                        transcript.verify((item,), deadlines=[])
                with pytest.raises(ValueError, match="cumulative read bound"):
                    transcript.verify(merges, deadlines=[])
        counts.clear()
        for _ in range(2):
            transcript.verify((merge,), deadlines=[])
        assert counts["ledger"] == counts["manifest"] == counts["batch"] == 0
        assert counts["part_checkpoint"] == counts["derive"] == (4 if record_count == 1 else 2)
        transcript.deadlines[:] = [datetime.now(UTC) - timedelta(seconds=1)]
        with pytest.raises(ValueError, match="expired|retention"):
            transcript.verify((merge,), deadlines=[datetime.now(UTC) + timedelta(minutes=5)])
    original_report = env.cloud.read_payload_bytes(
        ArtifactId(UUID(env.report_artifact.uri.removeprefix("artifact://")))
    )
    certificate = env.store.certify(
        env.binding.namespace,
        env.binding.run_id,
        report_ref=env.report_artifact.uri,
        report_digest=env.report_artifact.sha256,
        fence=env.fence,
        check_authority=lambda: None,
    )
    assert env.store.certified_report(
        env.binding.namespace,
        env.binding.run_id,
        now=datetime.now(UTC),
        check_authority=lambda: None,
    ) == (certificate, env.report_artifact.uri, original_report)
