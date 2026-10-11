"""Slices yield after durable units and never skip merge dependencies."""

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError

from tests.agent_core.test_coverage_executor import executor, setup_execution


def test_one_slice_commits_parts_before_merges(tmp_path):
    env = setup_execution(tmp_path, bodies=(("one", "two"), ("three",)))
    assert executor(env).execute_batch(fence=env.fence, limit=32) == (5, 5)
    assert [key.kind for key in env.store.accepted] == [
        "part", "part", "record_merge", "part", "record_merge",
    ]


def test_byte_slice_yields_then_fresh_executor_resumes(tmp_path):
    env = setup_execution(tmp_path, bodies=(("hello",), ("world",)))
    assert executor(env).execute_batch(fence=env.fence, max_input_bytes=6) == (4, 1)
    assert executor(env).execute_batch(fence=env.fence, max_input_bytes=6) == (4, 2)
    assert len(env.store.attempts) == 2


def test_oversized_legal_unit_makes_progress(tmp_path):
    env = setup_execution(tmp_path, bodies=(("hello",),))
    assert executor(env).execute_batch(fence=env.fence, max_input_bytes=1) == (2, 1)


def test_time_slice_finishes_current_unit_and_yields(tmp_path, monkeypatch):
    clock = iter((0.0, 3.0))
    monkeypatch.setattr("agent_core.application.coverage_executor.monotonic", lambda: next(clock))
    env = setup_execution(tmp_path, bodies=(("hello",),))
    assert executor(env).execute_batch(fence=env.fence, max_seconds=2) == (2, 1)
    assert len(env.store.accepted) == len(env.store.attempts) == 1


def test_revocation_between_units_stops_slice(tmp_path):
    env = setup_execution(tmp_path, bodies=(("hello",),))
    original = env.store.commit

    def revoke(request, *, fence):
        result = original(request, fence=fence)
        env.revoked = True
        return result

    env.store.commit = revoke
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        executor(env).execute_batch(fence=env.fence)
    assert len(env.store.accepted) == 1


@pytest.mark.parametrize("options", [
    {"limit": True}, {"limit": 0}, {"limit": 1001},
    {"max_input_bytes": True}, {"max_input_bytes": 0},
    {"max_seconds": True}, {"max_seconds": float("nan")},
    {"max_seconds": float("inf")}, {"max_seconds": 0}, {"max_seconds": 61},
])
def test_invalid_slice_has_no_attempts(tmp_path, options):
    env = setup_execution(tmp_path, bodies=(("hello",),))
    with pytest.raises(ValueError, match="work"):
        executor(env).execute_batch(fence=env.fence, **options)
    assert not env.store.attempts
