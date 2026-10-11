"""Qualified pre-first-batch initialization uses exact facts, never object proof."""
# ruff: noqa: F811

import pytest
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres.coverage import PostgresCoverageStore
from zebra_agent_worker.coverage_continuation import NATIVE_CONTINUATION_VERIFIER

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)
from tests.worker.test_coverage_model_acceptance import settled


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("damage", [None, "ledger", "revoked"])
def test_pre_first_acceptance_policy_reuse_keeps_fresh_integrity_and_authority(
    model_cloud, monkeypatch, damage,
):
    env = model_cloud
    settled(env)
    store = PostgresCoverageStore(
        env.dsn, deployment_namespace=NAMESPACE, artifacts=env.cloud,
        supported_model_profiles=(env.admission.model_profile,), execution_receipts=True,
        execution_receipt_verifier=NATIVE_CONTINUATION_VERIFIER,
        model_observation_deriver=derive_semantic_observation,
    )
    before = list(env.client.calls)
    original, reads = env.objects.read_version_verified, []

    def physical(*args):
        reads.append(args)
        assert damage == "ledger", "unchanged qualified initialization replayed objects"
        return original(*args)

    monkeypatch.setattr(env.objects, "read_version_verified", physical)
    if damage == "ledger":
        with env.database.connect() as connection:
            connection.execute("UPDATE coverage_model_ledger SET charged_tokens=charged_tokens+1")
    elif damage == "revoked":
        env.wire.revoked = True
    if damage is None:
        assert store.initialize_model_budget(env.binding, fence=env.fence) == env.policy
    else:
        with pytest.raises(ValueError):
            store.initialize_model_budget(env.binding, fence=env.fence)
    if damage == "ledger":
        assert reads  # Invalidated roots retain independent legacy replay/refusal.
    else:
        assert not reads and env.client.calls == before
    with env.database.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM coverage_execution_receipts",
        ).fetchone()["n"] == 0
