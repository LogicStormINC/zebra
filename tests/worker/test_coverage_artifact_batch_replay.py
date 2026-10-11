"""Native PG batch interruption: durable model checkpoints/charges survive buffering."""
# ruff: noqa: F811

from contextlib import nullcontext

import pytest
from agent_core.application.coverage_checks import PublishedCoverageRunner
from agent_core.application.coverage_executor import CoverageExecutor, observation_id
from agent_integrations.coverage_model import SemanticCoverageModel
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter

from tests.worker.coverage_model_cloud_fixtures import (
    check_authority,
    compose,
    dsn,  # noqa: F401
    model_cloud,  # noqa: F401
    postgres_dsn,  # noqa: F401
)
from tests.worker.test_coverage_model_acceptance import configured
from tests.worker.test_coverage_model_cloud import database_state


def executor(env, invocation):
    configured(env)
    host = env.host_source.host
    source = HostCoverageSnapshotAdapter(
        session_id=env.session, authority=env.host, history_ref=host.resource.resource_id,
        manifest=host.manifest, invoke=host.invoke, artifacts=env.cloud,
        publication_lock=nullcontext(),
    )
    runner = PublishedCoverageRunner((env.definition,), model=SemanticCoverageModel(
        model_profile=env.admission.model_profile,
        check_authority=lambda: check_authority(env), invoke_or_replay=invocation,
    ))

    def read(record, part):
        return source.read(env.binding.snapshot, record, part, authority=env.host)

    return CoverageExecutor(
        binding=env.binding, records=(env.record,), store=env.store, artifacts=env.cloud,
        read=read, runner=runner, budget=env.admission.execution_budget,
        check_authority=lambda: check_authority(env),
    )


@pytest.mark.parametrize("stage", ["before_publish", "after_publish"])
def test_interrupted_observation_batch_replays_without_second_http_or_charge(
    model_cloud, monkeypatch, stage,
):
    env = model_cloud
    invocation = compose(env)
    run = executor(env, invocation)
    original = env.cloud.store_payloads_immutable

    def interrupt(payloads):
        if stage == "after_publish":
            original(payloads)
        raise RuntimeError("interrupted observation batch")

    with monkeypatch.context() as patch:
        patch.setattr(env.cloud, "store_payloads_immutable", interrupt)
        with pytest.raises(RuntimeError, match="interrupted observation batch"):
            run.execute_batch(fence=env.fence, batch_commits=True)
    state = database_state(env)
    assert state[0] == (1, 30, 0) and len(env.requests) == 1
    assert env.store.counts(env.binding.namespace, env.binding.run_id) == (2, 0)
    stored = env.cloud.get_payload(observation_id(env.binding, env.key))
    assert (stored is not None) == (stage == "after_publish")
    fresh = compose(env, replacement=True)
    resumed = executor(env, fresh)
    assert resumed.execute_batch(fence=env.fence, batch_commits=True) == (2, 2)
    certificate, _ = resumed.publish_report(env.store, fence=env.fence)
    assert certificate is not None and len(env.requests) == 1
    after = database_state(env)
    assert after[0] == state[0] and after[1] == state[1]
