"""Bounded reuse of the frozen native Cloud fixture; no synthetic unit acceptance."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest
from agent_core.application.coverage_checks import merge_observations
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    decode_model_checkpoint,
)
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.identifiers import ArtifactId
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres.coverage_model_source import certify_model_budget
from agent_storage.postgres.coverage_transactions import lock_run

from tests.agent_integrations.test_coverage_model_invocation import invoke
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.worker.coverage_model_cloud_fixtures import compose, model_cloud
from tests.worker.test_coverage_model_acceptance import (
    configured,
    multipart_cloud,
    report_for,
    request_for,
)
from tests.worker.test_coverage_model_cloud import database_state


def source_counts(env):
    with psycopg.connect(env.dsn) as connection:
        return connection.execute(
            "SELECT count(*) FROM session_events WHERE deployment_namespace=%s AND session_id=%s",
            (NAMESPACE, env.binding.session_id),
        ).fetchone()[0]


def original_object(env):
    return next(
        key
        for key, item in env.client.objects.items()
        if item["Body"] == env.checkpoint.canonical_bytes
    )


def accounting_certification(env):
    # Accounting alone may pass this lower-layer check; it never issues a certificate.
    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, env.fence)
        at = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        return certify_model_budget(
            connection, NAMESPACE, env.binding, at=at, artifacts=env.artifacts
        )


@pytest.fixture
def proof_env(dsn):
    generators = []
    built = []

    def build(*, runtime=120, retention_seconds=None, multipart=False):
        generator = model_cloud.__wrapped__(dsn, SimpleNamespace(param=runtime))
        generators.append(generator)
        env = next(generator)
        if multipart:
            multipart_cloud.__wrapped__(env)
        component = compose(env)
        original_publish = env.cloud.store_payload_immutable
        env.payloads = []

        def publish(payload, *, artifact_id):
            if payload.kind == MODEL_CHECKPOINT_KIND:
                if retention_seconds is not None and not env.payloads:
                    payload = payload.model_copy(
                        update={
                            "retained_until": datetime.now(UTC)
                            + timedelta(seconds=retention_seconds)
                        }
                    )
                env.payloads.append(payload)
            return original_publish(payload, artifact_id=artifact_id)

        env.cloud.store_payload_immutable = publish
        observations, receipts = [], []
        for key in expected_units(env.binding.contract, (env.record,)):
            if key.kind != "part":
                continue
            env.key = key
            env.reply["choices"][0]["message"]["content"] = json.dumps(
                {
                    "key": key.model_dump(mode="json"),
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
                if CoverageModelUsageReceipt.model_validate(row[1]).reservation.key == key
            )
            identifier = ArtifactId(UUID(receipt.checkpoint_ref.removeprefix("artifact://")))
            body = env.cloud.read_payload_bytes(identifier)
            observation = derive_semantic_observation(
                body, receipt, env.definition, key, env.record
            )
            env.store.commit(request_for(env, observation), fence=env.fence)
            observations.append(observation)
            receipts.append(receipt)
        key = next(
            k
            for k in expected_units(env.binding.contract, (env.record,))
            if k.kind == "record_merge"
        )
        merge = merge_observations(key, tuple(p.id for p in env.record.parts), tuple(observations))
        env.request = request_for(env, merge)
        env.store.commit(env.request, fence=env.fence)
        ref, digest = report_for(env, (*observations, merge))
        env.report_artifact = SimpleNamespace(uri=ref, sha256=digest)
        env.artifacts = env.cloud
        env.receipts = tuple(receipts)
        env.checkpoint = decode_model_checkpoint(env.payloads[0].payload)
        env.retention_deadline = env.payloads[0].retained_until
        assert len(env.requests) == len(receipts)
        built.append(env)
        return env

    yield build
    for generator in reversed(generators):
        generator.close()
    assert all(len(env.requests) == len(env.receipts) for env in built)
