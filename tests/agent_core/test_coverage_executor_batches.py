"""Bounded result batches preserve durable merge prerequisites and crash replay."""

from types import SimpleNamespace

import pytest
from agent_core.ports.artifact_payload_store import ImmutableArtifactPayloadBatchStorePort

from tests.agent_core.test_coverage_executor import executor, setup_execution


def test_one_page_commits_parts_then_merges_without_per_unit_result_artifacts(tmp_path):
    env = setup_execution(tmp_path, bodies=(("risk",),) * 9)
    commits, commit = [], env.store.commit

    def checked(request, *, fence):
        kinds = {result.key.kind for result in request.results}
        assert len(kinds) == 1
        if kinds == {"record_merge"}:
            assert len(env.store.accepted) == 9
        commits.append(request)
        return commit(request, fence=fence)

    env.store.commit = checked
    assert executor(env).execute_batch(fence=env.fence, batch_commits=True) == (18, 18)
    assert [len(request.results) for request in commits] == [9, 9]
    assert len(env.store.receipts) == 2
    assert len(env.store.attempts) == 18


def test_crash_before_batch_commit_reuses_governed_observations_on_restart(tmp_path):
    env = setup_execution(tmp_path, bodies=(("risk",),) * 3)
    original = env.runner.run
    invoked = []

    def runner(key, bodies, *, prior):
        invoked.append(key)
        if len(invoked) == 2:
            raise RuntimeError("interrupted transport")
        return original(key, bodies, prior=prior)

    env.runner = SimpleNamespace(run=runner)
    with pytest.raises(RuntimeError, match="interrupted transport"):
        executor(env).execute_batch(fence=env.fence, batch_commits=True)
    assert not env.store.accepted
    assert not env.store.receipts
    first = invoked[0]
    assert executor(env).execute_batch(fence=env.fence, batch_commits=True) == (6, 6)
    assert invoked.count(first) == 1


def test_byte_limit_flushes_bounded_page_and_keeps_later_work_missing(tmp_path):
    env = setup_execution(tmp_path, bodies=(("risk",),) * 9)
    assert executor(env).execute_batch(
        fence=env.fence, max_input_bytes=8, batch_commits=True,
    ) == (18, 2)
    assert len(env.store.receipts) == 1
    assert len(next(iter(env.store.pages))) == 18
    assert len(env.store.attempts) == 2
    assert executor(env).execute_batch(fence=env.fence, batch_commits=True) == (18, 18)


def test_lost_batch_response_does_not_repeat_accepted_units(tmp_path):
    env = setup_execution(tmp_path, bodies=(("risk",),) * 3)
    env.store.lose_response = True
    with pytest.raises(RuntimeError, match="lost commit response"):
        executor(env).execute_batch(fence=env.fence, batch_commits=True)
    assert len(env.store.accepted) == 3
    assert executor(env).execute_batch(fence=env.fence, batch_commits=True) == (6, 6)
    assert len(env.store.attempts) == 6
    assert len(env.store.receipts) == 2


def test_optional_batch_port_publishes_observations_with_result_before_acceptance(tmp_path):
    env = setup_execution(tmp_path, bodies=(("risk",),) * 9)
    batches = []

    def store_many(payloads):
        assert len(payloads) <= 1000
        assert sum(len(payload.payload) for _, payload in payloads) <= 32 * 1024 * 1024
        batches.append(payloads)
        return tuple(env.artifacts.store_payload_immutable(payload, artifact_id=identifier)
                     for identifier, payload in payloads)

    env.artifacts.store_payloads_immutable = store_many
    assert isinstance(env.artifacts, ImmutableArtifactPayloadBatchStorePort)
    assert executor(env).execute_batch(fence=env.fence, batch_commits=True) == (18, 18)
    assert [len(batch) for batch in batches] == [10, 10]
    assert all([payload.kind for _, payload in batch] == ["coverage_observation"] * 9
               + ["coverage_results"] for batch in batches)
    assert len(env.store.receipts) == 2 and len(env.store.attempts) == 18


@pytest.mark.parametrize("failure", ["partial", "wrong_digest", "wrong_order"])
def test_batch_metadata_contract_failure_never_accepts_units(tmp_path, failure):
    env = setup_execution(tmp_path, bodies=(("risk",),) * 3)

    def corrupt(payloads):
        result = tuple(env.artifacts.store_payload_immutable(payload, artifact_id=identifier)
                       for identifier, payload in payloads)
        if failure == "partial":
            return result[:-1]
        if failure == "wrong_order":
            return result[::-1]
        return (result[0].model_copy(update={"sha256": "0" * 64}), *result[1:])

    env.artifacts.store_payloads_immutable = corrupt
    with pytest.raises(ValueError, match="Artifact batch"):
        executor(env).execute_batch(fence=env.fence, batch_commits=True)
    assert not env.store.accepted and not env.store.receipts
