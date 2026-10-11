"""Typed copies must retain illicit raw fields at every observation boundary."""

from types import SimpleNamespace

import pytest
from agent_core.application.coverage_checks import PublishedCoverageRunner, merge_observations
from agent_core.domain.coverage_execution import CoverageObservation, CoverageQuote
from agent_core.domain.coverage_validation import AcceptedCoverageUnit, result_set_digest
from agent_core.ports.coverage import CoverageCommit
from agent_storage.postgres.coverage import PostgresCoverageStore

from tests.agent_core.test_coverage_executor import executor, setup_execution


def forged(key, defect):
    observation = CoverageObservation(key=key, outcome="clear", summary="clear")
    if defect == "extra":
        observation.__dict__["illicit"] = "lost by model_dump"
    elif defect == "key_extra":
        observation.key.__dict__["illicit"] = True
    else:
        quote = CoverageQuote(part_id=key.part_id, start=0, end=1, text="r")
        if defect == "quote_extra":
            quote.__dict__["illicit"] = True
        else:
            quote = quote.model_copy(update={"start": False})
        observation = observation.model_copy(update={"quotes": (quote,)})
    return observation


@pytest.mark.parametrize("defect", ["extra", "key_extra", "quote_extra", "quote_type"])
@pytest.mark.parametrize("boundary", ["runner", "executor"])
def test_raw_observation_rejected_before_publication(tmp_path, defect, boundary):
    env = setup_execution(tmp_path, bodies=(("risk",),), model=lambda *args: None)
    key = env.store.units[0].model_copy()
    bad = forged(key, defect)
    if boundary == "runner":
        with pytest.raises(ValueError):
            PublishedCoverageRunner(
                tuple(env.runner.definitions.values()), model=lambda *args: bad
            ).run(env.store.units[0], {key.part_id: "risk"}, prior=())
    else:
        env.runner = SimpleNamespace(run=lambda *args, **kwargs: bad)
        with pytest.raises(ValueError):
            executor(env).execute_batch(fence=env.fence, limit=1)
        assert env.store.accepted == {}


@pytest.mark.parametrize("target", ["request", "result", "key", "outcome"])
def test_raw_commit_rejected_before_database(tmp_path, target):
    env = setup_execution(tmp_path, bodies=(("risk",),))
    result = AcceptedCoverageUnit(
        key=env.store.units[0].model_copy(), result_digest="a" * 64, outcome="clear"
    )
    request = CoverageCommit(
        namespace=env.binding.namespace,
        session_id=env.binding.session_id,
        task_id=env.binding.task_id,
        run_id=env.binding.run_id,
        snapshot_id=env.binding.snapshot.snapshot_id,
        contract_digest=env.binding.contract.digest,
        manifest_digest=env.binding.snapshot.manifest_digest,
        commit_key="test",
        result_artifact_ref=env.binding.snapshot.manifest_artifact_ref,
        result_artifact_digest=result_set_digest((result,)),
        results=(result,),
    )
    if target == "outcome":
        result.__dict__["outcome"] = False
    else:
        {"request": request, "result": result, "key": result.key}[target].__dict__["illicit"] = True
    store = PostgresCoverageStore("unused", deployment_namespace="test", artifacts=env.artifacts)
    with pytest.raises(ValueError):
        store.commit(request, fence=env.fence)


def test_shared_merge_rejects_reordered_parts(tmp_path):
    env = setup_execution(tmp_path)
    keys = env.store.units
    prior = tuple(
        CoverageObservation(key=key, outcome="clear", summary="clear")
        for key in keys
        if key.kind == "part"
    )
    merged = merge_observations(keys[-1], tuple(item.key.part_id for item in prior), prior)
    assert merged.part_result_digests == tuple(item.digest for item in prior)
    with pytest.raises(ValueError):
        merge_observations(
            keys[-1], tuple(item.key.part_id for item in prior), tuple(reversed(prior))
        )
