"""Locked native rebuild reuses only its own proof phase and rolls back failures."""

from collections import Counter

import pytest
from agent_core.domain.events import EventType
from agent_storage.postgres import coverage as coverage
from agent_storage.postgres import coverage_model_acceptance as acceptance
from agent_storage.postgres import coverage_model_verification as verification

from tests.agent_storage.coverage_model_proof_fixtures import proof_env  # noqa: F401
from tests.agent_storage.test_coverage_model_verification_native import two_records
from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.coverage_model_cloud_fixtures import model_cloud  # noqa: F401
from tests.worker.test_coverage_model_acceptance import history
from tests.worker.test_coverage_model_rebuild import projection_state, remove_projections


@pytest.mark.parametrize("record_count", [1, 2])
def test_rebuild_local_transcript_repairs_missing_projections_and_rolls_back(
    request, monkeypatch, record_count
):
    env = (
        request.getfixturevalue("proof_env")(multipart=True)
        if record_count == 1
        else two_records(request.getfixturevalue("model_cloud"))
    )
    before, events = projection_state(env), history(env)
    remove_projections(env, "all")
    empty = projection_state(env)
    real_verify = acceptance.verify_results

    def late_failure(*args):
        real_verify(*args)
        raise ValueError("native late proof failure")

    with monkeypatch.context() as failure:
        failure.setattr(acceptance, "verify_results", late_failure)
        with pytest.raises(ValueError, match="native late proof failure"):
            env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert projection_state(env) == empty and history(env) == events
    counts = Counter()

    def count(module, name):
        original = getattr(module, name)

        def wrapped(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapped)

    count(verification, "replay_model")
    count(verification, "read_manifest")
    count(verification, "replay_request")
    count(acceptance, "verify_results")
    original_seed = coverage.seed_run

    def seed(*args):
        assert counts["replay_model"] == 1
        return original_seed(*args)

    monkeypatch.setattr(coverage, "seed_run", seed)
    watermark = max(
        event.sequence for event in events
        if event.event_type == EventType.COVERAGE_BATCH_ACCEPTED
    )
    assert env.store.rebuild(env.binding.namespace, env.binding.run_id) == watermark
    assert counts == Counter(
        replay_model=1, read_manifest=1, replay_request=2 + record_count,
        verify_results=2 + record_count,
    )
    assert projection_state(env) == before and history(env) == events
